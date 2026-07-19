"""Tests for src/layers/layer_4_compare_values (equality/accepted/logic/run/output.py).

Layers 1-3 are built on separate branches, so their LayerResults are
hand-constructed here per the fixed interface contract: layer 1's extras carry
df_left/df_right/files, layer 2's extras carry common_columns, layer 3's extras
carry inner_keys (the matched, non-duplicate composite keys, D8).
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from src.layers.layer_4_compare_values import (
    AcceptedDifferences,
    align_frames,
    compare_cells,
    export,
    flag_accepted,
    load_accepted_differences,
    report,
    run,
    value_verdict,
    values_equal,
)
from src.utils.execution import ExecutionContext, LayerResult
from src.utils.keys import duplicate_mask, key_frame, unique_keys


# --------------------------------------------------------------------------
# Fixture / LayerResult construction helpers
# --------------------------------------------------------------------------


def _load_pair(pair: str, fixtures_dir):
    df_left = pd.read_csv(fixtures_dir / f"{pair}_left.csv")
    df_right = pd.read_csv(fixtures_dir / f"{pair}_right.csv")
    return df_left, df_right


def _inner_keys(df_left, df_right, key_columns) -> set:
    """Matched keys minus anything duplicated on either side (layer 3's D8 rule)."""
    left = unique_keys(df_left, key_columns)
    right = unique_keys(df_right, key_columns)
    dup_left = set(key_frame(df_left, key_columns)[duplicate_mask(df_left, key_columns)])
    dup_right = set(key_frame(df_right, key_columns)[duplicate_mask(df_right, key_columns)])
    return (left & right) - dup_left - dup_right


def _layer1_result(df_left, df_right, left_path="left.csv", right_path="right.csv") -> LayerResult:
    return LayerResult(
        name="layer_1_read",
        verdict="success",
        data=pd.DataFrame(),
        extras={
            "df_left": df_left,
            "df_right": df_right,
            "left_encoding": "utf-8",
            "right_encoding": "utf-8",
            "files": {
                "left": {"path": left_path, "encoding": "utf-8"},
                "right": {"path": right_path, "encoding": "utf-8"},
            },
        },
    )


def _layer2_result(common_columns) -> LayerResult:
    return LayerResult(
        name="layer_2_compare_columns",
        verdict="success",
        data=pd.DataFrame(),
        extras={"common_columns": list(common_columns), "summary": {}},
    )


def _layer3_result(inner_keys) -> LayerResult:
    return LayerResult(
        name="layer_3_compare_rows",
        verdict="completed-with-differences",
        data=pd.DataFrame(),
        extras={"inner_keys": set(inner_keys), "summary": {}},
    )


def _config(make_config, *, left="left.csv", right="right.csv", key_columns=("id",), tolerances=None, accepted_path=None):
    config = make_config(left=left, right=right)
    config.KEY_COLUMNS = list(key_columns)
    config.PER_COLUMN_NUMERIC_TOLERANCE = dict(tolerances or {})
    config.ACCEPTED_DIFFERENCES_PATH = accepted_path
    return config


def _write_accepted(path, rows):
    """Write an accepted_differences.csv with the standard header + given rows."""
    df = pd.DataFrame(rows, columns=["column", "reason", "example_left", "example_right"])
    df.to_csv(path, index=False)
    return path


def _results_for(make_config, pair, fixtures_dir, **config_kwargs):
    """Build (layer1, layer2, layer3, config) for a fixture pair."""
    df_left, df_right = _load_pair(pair, fixtures_dir)
    common_columns = [c for c in df_left.columns if c in set(df_right.columns)]
    layer1 = _layer1_result(
        df_left,
        df_right,
        left_path=str(fixtures_dir / f"{pair}_left.csv"),
        right_path=str(fixtures_dir / f"{pair}_right.csv"),
    )
    layer2 = _layer2_result(common_columns)
    layer3 = _layer3_result(_inner_keys(df_left, df_right, ["id"]))
    config = _config(
        make_config,
        left=fixtures_dir / f"{pair}_left.csv",
        right=fixtures_dir / f"{pair}_right.csv",
        **config_kwargs,
    )
    return layer1, layer2, layer3, config


# --------------------------------------------------------------------------
# values_equal -- the D9 matrix (where subtle correctness lives)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "left,right,tol,expected",
    [
        # NaN / missing handling
        (np.nan, np.nan, 0.0, True),          # both missing -> equal
        (None, None, 0.0, True),
        (np.nan, 1, 0.0, False),              # exactly one missing -> not equal
        (1, np.nan, 0.0, False),
        # numeric coercion (int vs float, numeric strings)
        (1, 1.0, 0.0, True),                  # 1 == 1.0
        ("1", 1, 0.0, True),                  # numeric string vs number
        ("1.0", "1", 0.0, True),
        (200, 205, 0.0, False),               # real numeric difference
        # per-column tolerance
        (200, 205, 5.0, True),                # within tolerance
        (200, 205, 4.0, False),               # outside tolerance
        (200, 210, 10.0, True),               # boundary: abs diff == tol
        # string comparison + trailing-whitespace stripping (D9: trailing only)
        ("Bob", "Bob", 0.0, True),
        ("Bob", "Robert", 0.0, False),
        ("abc ", "abc", 0.0, True),           # trailing whitespace ignored
        (" abc", "abc", 0.0, False),          # leading whitespace is significant
        # booleans are not numbers (True must not equal 1)
        (True, 1, 0.0, False),
        (True, True, 0.0, True),
        # pathological "nan"/"inf" strings compare as text, not as floats
        ("nan", "nan", 0.0, True),
        ("inf", "inf", 0.0, True),
        # dates are compared as text, never format-normalized
        ("2026-01-01", "2026-01-01", 0.0, True),
        ("2026-01-01", "2026-1-1", 0.0, False),
    ],
)
def test_values_equal(left, right, tol, expected):
    assert values_equal(left, right, tol) is expected


# --------------------------------------------------------------------------
# align_frames
# --------------------------------------------------------------------------


def test_align_frames_filters_projects_and_sorts(fixtures_dir):
    df_left, df_right = _load_pair("identical", fixtures_dir)
    inner = _inner_keys(df_left, df_right, ["id"])

    left_aligned, right_aligned = align_frames(
        df_left, df_right, ["id", "name", "value"], ["id"], inner
    )

    assert list(left_aligned.columns) == ["id", "name", "value"]
    assert left_aligned["id"].tolist() == [1, 2, 3, 4, 5]
    assert right_aligned["id"].tolist() == [1, 2, 3, 4, 5]


def test_align_frames_excludes_non_inner_and_row_aligns_by_key():
    """Left/right rows in different orders + a non-inner key are aligned so that
    position i refers to the same key on both sides."""
    df_left = pd.DataFrame({"id": [3, 1, 2], "name": ["C", "A", "B"]})
    df_right = pd.DataFrame({"id": [2, 1, 9], "name": ["B", "A", "Z"]})
    inner = {("1",), ("2",)}  # id 3 is left-only, id 9 right-only -> excluded

    left_aligned, right_aligned = align_frames(df_left, df_right, ["id", "name"], ["id"], inner)

    assert left_aligned["id"].tolist() == [1, 2]
    assert right_aligned["id"].tolist() == [1, 2]
    assert left_aligned["name"].tolist() == ["A", "B"]
    assert right_aligned["name"].tolist() == ["A", "B"]


# --------------------------------------------------------------------------
# compare_cells
# --------------------------------------------------------------------------


def test_compare_cells_value_drift_produces_expected_diffs(fixtures_dir):
    df_left, df_right = _load_pair("value_drift", fixtures_dir)
    inner = _inner_keys(df_left, df_right, ["id"])
    left_aligned, right_aligned = align_frames(df_left, df_right, ["id", "name", "value"], ["id"], inner)

    diffs = compare_cells(left_aligned, right_aligned, ["id", "name", "value"], ["id"])

    assert list(diffs.columns) == ["id", "column", "value_left", "value_right"]
    # Row-major, sorted by key: id2 name, id2 value, id4 value.
    assert diffs["id"].tolist() == [2, 2, 4]
    assert diffs["column"].tolist() == ["name", "value", "value"]
    assert diffs["value_left"].tolist() == ["Bob", 200, 400]
    assert diffs["value_right"].tolist() == ["Robert", 205, 410]


def test_compare_cells_identical_has_no_diffs(fixtures_dir):
    df_left, df_right = _load_pair("identical", fixtures_dir)
    inner = _inner_keys(df_left, df_right, ["id"])
    left_aligned, right_aligned = align_frames(df_left, df_right, ["id", "name", "value"], ["id"], inner)

    diffs = compare_cells(left_aligned, right_aligned, ["id", "name", "value"], ["id"])

    assert diffs.empty
    assert list(diffs.columns) == ["id", "column", "value_left", "value_right"]


def test_compare_cells_never_diffs_key_columns():
    """Key columns are the row identity, never emitted as a differing column."""
    left_aligned = pd.DataFrame({"id": [1, 2], "name": ["A", "B"]})
    right_aligned = pd.DataFrame({"id": [1, 2], "name": ["A", "Z"]})

    diffs = compare_cells(left_aligned, right_aligned, ["id", "name"], ["id"])

    assert diffs["column"].tolist() == ["name"]
    assert "id" not in diffs["column"].tolist()


def test_compare_cells_tolerance_suppresses_numeric_diff():
    left_aligned = pd.DataFrame({"id": [1], "value": [200]})
    right_aligned = pd.DataFrame({"id": [1], "value": [205]})

    within = compare_cells(left_aligned, right_aligned, ["id", "value"], ["id"], {"value": 10})
    outside = compare_cells(left_aligned, right_aligned, ["id", "value"], ["id"], {"value": 1})

    assert within.empty
    assert outside["column"].tolist() == ["value"]


def test_compare_cells_nan_equals_nan_but_nan_vs_value_differs():
    left_aligned = pd.DataFrame({"id": [1, 2], "note": [np.nan, np.nan]})
    right_aligned = pd.DataFrame({"id": [1, 2], "note": [np.nan, "present"]})

    diffs = compare_cells(left_aligned, right_aligned, ["id", "note"], ["id"])

    assert diffs["id"].tolist() == [2]  # id1 NaN==NaN (no diff); id2 NaN vs value (diff)
    assert diffs["value_right"].tolist() == ["present"]


# --------------------------------------------------------------------------
# load_accepted_differences
# --------------------------------------------------------------------------


def test_load_accepted_none_path():
    accepted = load_accepted_differences(None)
    assert accepted.columns == ()
    assert "nothing is accepted" in accepted.note


def test_load_accepted_missing_file(tmp_path):
    accepted = load_accepted_differences(tmp_path / "does_not_exist.csv")
    assert accepted.columns == ()
    assert "No accepted-differences file" in accepted.note


def test_load_accepted_header_only_file(tmp_path):
    """A present-but-empty (header-only) policy file = nothing accepted, logged."""
    path = tmp_path / "accepted.csv"
    path.write_text("column,reason,example_left,example_right\n", encoding="utf-8")

    accepted = load_accepted_differences(path)

    assert accepted.columns == ()
    assert "no accepted columns" in accepted.note


def test_load_accepted_populated_file(tmp_path):
    path = _write_accepted(
        tmp_path / "accepted.csv",
        [
            {"column": "value", "reason": "rounding", "example_left": 200, "example_right": 205},
            {"column": "name", "reason": "rename", "example_left": "Bob", "example_right": "Robert"},
        ],
    )

    accepted = load_accepted_differences(path)

    assert accepted.columns == ("value", "name")
    assert accepted.reasons == {"value": "rounding", "name": "rename"}
    assert "Loaded 2 accepted column(s)" in accepted.note


# --------------------------------------------------------------------------
# flag_accepted
# --------------------------------------------------------------------------


def test_flag_accepted_marks_membership():
    diffs = pd.DataFrame(
        {"id": [2, 2, 4], "column": ["name", "value", "value"],
         "value_left": ["Bob", 200, 400], "value_right": ["Robert", 205, 410]}
    )

    flagged = flag_accepted(diffs, ["value"])

    assert flagged["acceptable_difference"].tolist() == [False, True, True]


def test_flag_accepted_empty_table_gets_bool_column():
    diffs = pd.DataFrame(columns=["id", "column", "value_left", "value_right"])

    flagged = flag_accepted(diffs, ["value"])

    assert "acceptable_difference" in flagged.columns
    assert flagged.empty
    assert flagged["acceptable_difference"].dtype == bool


# --------------------------------------------------------------------------
# value_verdict (D3)
# --------------------------------------------------------------------------


def test_value_verdict_success_when_no_diffs():
    empty = flag_accepted(pd.DataFrame(columns=["id", "column", "value_left", "value_right"]), [])
    assert value_verdict(empty) == "success"


def test_value_verdict_success_when_all_accepted():
    diffs = flag_accepted(
        pd.DataFrame({"id": [2], "column": ["value"], "value_left": [200], "value_right": [205]}),
        ["value"],
    )
    assert value_verdict(diffs) == "success"


def test_value_verdict_failed_when_any_non_accepted():
    diffs = flag_accepted(
        pd.DataFrame(
            {"id": [2, 2], "column": ["name", "value"], "value_left": ["Bob", 200], "value_right": ["Robert", 205]}
        ),
        ["value"],  # name is not accepted
    )
    assert value_verdict(diffs) == "failed"


# --------------------------------------------------------------------------
# run() -- integration over hand-built layer1/2/3 LayerResults
# --------------------------------------------------------------------------


def test_run_identical_is_success(make_config, fixtures_dir):
    layer1, layer2, layer3, config = _results_for(make_config, "identical", fixtures_dir)

    result = run(layer1, layer2, layer3, config)

    assert result.name == "layer_4_compare_values"
    assert result.verdict == "success"
    assert result.data.empty
    assert list(result.data.columns) == ["id", "column", "value_left", "value_right", "acceptable_difference"]
    assert result.extras["summary"]["diff_counts"] == {}
    assert result.extras["summary"]["total_differences"] == 0
    assert result.extras["summary"]["compared_rows"] == 5
    assert result.extras["summary"]["compared_columns"] == 2


def test_run_value_drift_no_accepted_is_failed(make_config, fixtures_dir):
    layer1, layer2, layer3, config = _results_for(make_config, "value_drift", fixtures_dir)

    result = run(layer1, layer2, layer3, config)

    assert result.verdict == "failed"
    assert len(result.data) == 3
    assert result.data["acceptable_difference"].tolist() == [False, False, False]
    summary = result.extras["summary"]
    assert summary["diff_counts"] == {"name": 1, "value": 2}
    assert summary["total_differences"] == 3
    assert summary["accepted_differences"] == 0
    assert summary["non_accepted_differences"] == 3
    assert summary["accepted_columns"] == []


def test_run_value_drift_all_accepted_is_success(make_config, fixtures_dir, tmp_path):
    """D3: every difference is in an accepted column -> green success."""
    accepted_path = _write_accepted(
        tmp_path / "accepted.csv",
        [
            {"column": "name", "reason": "renamed", "example_left": "Bob", "example_right": "Robert"},
            {"column": "value", "reason": "rounded", "example_left": 200, "example_right": 205},
        ],
    )
    layer1, layer2, layer3, config = _results_for(
        make_config, "value_drift", fixtures_dir, accepted_path=accepted_path
    )

    result = run(layer1, layer2, layer3, config)

    assert result.verdict == "success"
    assert len(result.data) == 3  # differences are still listed...
    assert result.data["acceptable_difference"].tolist() == [True, True, True]  # ...just all accepted
    summary = result.extras["summary"]
    assert summary["accepted_differences"] == 3
    assert summary["non_accepted_differences"] == 0
    assert set(summary["accepted_columns"]) == {"name", "value"}


def test_run_value_drift_partial_accepted_is_failed(make_config, fixtures_dir, tmp_path):
    """Only 'value' accepted; the 'name' difference remains non-accepted -> failed."""
    accepted_path = _write_accepted(
        tmp_path / "accepted.csv",
        [{"column": "value", "reason": "rounded", "example_left": 200, "example_right": 205}],
    )
    layer1, layer2, layer3, config = _results_for(
        make_config, "value_drift", fixtures_dir, accepted_path=accepted_path
    )

    result = run(layer1, layer2, layer3, config)

    assert result.verdict == "failed"
    summary = result.extras["summary"]
    assert summary["accepted_differences"] == 2  # both 'value' diffs
    assert summary["non_accepted_differences"] == 1  # the 'name' diff


def test_run_column_drift_compares_only_common_columns(make_config, fixtures_dir):
    """status/department are non-common and must be ignored; the common columns
    are identical, so the value comparison succeeds."""
    layer1, layer2, layer3, config = _results_for(make_config, "column_drift", fixtures_dir)

    result = run(layer1, layer2, layer3, config)

    assert result.verdict == "success"
    assert result.data.empty
    assert result.extras["compared_columns"] == ["name", "value"]


def test_run_tolerance_suppresses_diffs(make_config, fixtures_dir):
    layer1, layer2, layer3, config = _results_for(
        make_config, "value_drift", fixtures_dir, tolerances={"value": 10}
    )

    result = run(layer1, layer2, layer3, config)

    # 200 vs 205 and 400 vs 410 are both within tol=10; only the 'name' diff remains.
    assert result.extras["summary"]["diff_counts"] == {"name": 1}
    assert result.verdict == "failed"  # 'name' is still a non-accepted diff


# --------------------------------------------------------------------------
# export() -- real CSV/TXT via ExecutionContext
# --------------------------------------------------------------------------


def test_export_writes_csv_and_txt(make_config, fixtures_dir):
    layer1, layer2, layer3, config = _results_for(make_config, "value_drift", fixtures_dir)
    ctx = ExecutionContext.create(config, now=datetime(2026, 7, 18, 12, 0, 0))
    ctx.record(layer1)

    result = run(layer1, layer2, layer3, config)
    export(result, ctx)

    csv_path = ctx.csv_path(result.name)
    txt_path = ctx.txt_path(result.name)
    assert csv_path.exists() and txt_path.exists()

    csv_df = pd.read_csv(csv_path)
    assert list(csv_df.columns) == ["id", "column", "value_left", "value_right", "acceptable_difference"]
    assert csv_df["column"].tolist() == ["name", "value", "value"]

    txt = txt_path.read_text(encoding="utf-8")
    assert "Layer 4 - Compare Values" in txt
    assert "Verdict:    failed" in txt
    assert "value_drift_left.csv" in txt
    assert "encoding: utf-8" in txt


def test_export_writes_artifacts_even_on_failed_verdict(make_config, fixtures_dir):
    """architecture.md's contract: artifacts written before the pipeline stops, on failure too."""
    layer1, layer2, layer3, config = _results_for(make_config, "value_drift", fixtures_dir)
    ctx = ExecutionContext.create(config)
    ctx.record(layer1)

    result = run(layer1, layer2, layer3, config)
    assert result.verdict == "failed"

    export(result, ctx)
    assert ctx.csv_path(result.name).exists()
    assert ctx.txt_path(result.name).exists()


# --------------------------------------------------------------------------
# report() -- real PDF via ExecutionContext + ReportBuilder
# --------------------------------------------------------------------------


def test_report_writes_nonempty_pdf_on_failure(make_config, fixtures_dir):
    layer1, layer2, layer3, config = _results_for(make_config, "value_drift", fixtures_dir)
    ctx = ExecutionContext.create(config)
    ctx.record(layer1)

    result = run(layer1, layer2, layer3, config)
    export(result, ctx)
    report(result, ctx)

    pdf_path = ctx.pdf_path(result.name)
    assert pdf_path.exists()
    assert pdf_path.read_bytes().startswith(b"%PDF-")


def test_report_success_and_accepted_reasons_pdf(make_config, fixtures_dir, tmp_path):
    """Exercises the grey-bar + accepted-reasons rendering path (all accepted)."""
    accepted_path = _write_accepted(
        tmp_path / "accepted.csv",
        [
            {"column": "name", "reason": "renamed upstream", "example_left": "Bob", "example_right": "Robert"},
            {"column": "value", "reason": "rounded to 5s", "example_left": 200, "example_right": 205},
        ],
    )
    layer1, layer2, layer3, config = _results_for(
        make_config, "value_drift", fixtures_dir, accepted_path=accepted_path
    )
    ctx = ExecutionContext.create(config)
    ctx.record(layer1)

    result = run(layer1, layer2, layer3, config)
    assert result.verdict == "success"
    export(result, ctx)
    report(result, ctx)

    pdf_path = ctx.pdf_path(result.name)
    assert pdf_path.exists()
    assert pdf_path.read_bytes().startswith(b"%PDF-")


def test_report_identical_no_diffs_pdf(make_config, fixtures_dir):
    layer1, layer2, layer3, config = _results_for(make_config, "identical", fixtures_dir)
    ctx = ExecutionContext.create(config)
    ctx.record(layer1)

    result = run(layer1, layer2, layer3, config)
    export(result, ctx)
    report(result, ctx)

    assert ctx.pdf_path(result.name).read_bytes().startswith(b"%PDF-")
