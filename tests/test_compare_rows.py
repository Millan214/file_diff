"""Tests for src/layers/layer_3_compare_rows (compare_rows.py + gate.py).

Layer 1 and layer 2 are being built in parallel on separate branches, so
their LayerResults are hand-constructed here per the fixed interface
contract: layer 1's extras carry df_left/df_right/left_encoding/
right_encoding/files, layer 2's extras carry common_columns.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from src.layers.layer_3_compare_rows.compare_rows import (
    classify_keys,
    export,
    find_duplicates,
    report,
    row_verdict,
    run,
)
from src.layers.layer_3_compare_rows.gate import decide
from src.utils.execution import ExecutionContext, LayerResult
from src.utils.keys import unique_keys


# --------------------------------------------------------------------------
# Fixture-construction helpers
# --------------------------------------------------------------------------


def _layer1_result(pair: str, fixtures_dir) -> LayerResult:
    left_path = fixtures_dir / f"{pair}_left.csv"
    right_path = fixtures_dir / f"{pair}_right.csv"
    df_left = pd.read_csv(left_path)
    df_right = pd.read_csv(right_path)
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
                "left": {"path": str(left_path), "encoding": "utf-8"},
                "right": {"path": str(right_path), "encoding": "utf-8"},
            },
        },
    )


def _layer2_result(common_columns: list[str]) -> LayerResult:
    return LayerResult(
        name="layer_2_compare_columns",
        verdict="success",
        data=pd.DataFrame(),
        extras={"common_columns": common_columns, "summary": {}},
    )


def _config(make_config, pair: str, fixtures_dir):
    config = make_config(
        left=fixtures_dir / f"{pair}_left.csv",
        right=fixtures_dir / f"{pair}_right.csv",
    )
    config.KEY_COLUMNS = ["id"]
    return config


# --------------------------------------------------------------------------
# find_duplicates
# --------------------------------------------------------------------------


def test_find_duplicates_detects_repeated_key(fixtures_dir):
    df = pd.read_csv(fixtures_dir / "row_drift_dupes_left.csv")
    assert find_duplicates(df, ["id"]) == {("1",)}


def test_find_duplicates_empty_when_no_repeats(fixtures_dir):
    df = pd.read_csv(fixtures_dir / "row_drift_dupes_right.csv")
    assert find_duplicates(df, ["id"]) == set()


def test_find_duplicates_identical_fixture_has_none(fixtures_dir):
    df = pd.read_csv(fixtures_dir / "identical_left.csv")
    assert find_duplicates(df, ["id"]) == set()


# --------------------------------------------------------------------------
# classify_keys
# --------------------------------------------------------------------------


def test_classify_keys_all_six_categories():
    """Synthetic key sets exercising every bucket at once:
    1 -> left_only, 8 -> right_only, 2/6/7 -> inner,
    3 -> duplicate_left, 4 -> duplicate_right, 5 -> duplicate_both.
    """
    left_keys = {1, 2, 3, 4, 5, 6, 7}
    right_keys = {2, 3, 4, 5, 6, 7, 8}
    dup_left_keys = {3, 5}
    dup_right_keys = {4, 5}

    result = classify_keys(left_keys, right_keys, dup_left_keys, dup_right_keys)

    assert result["left_only"] == {1}
    assert result["right_only"] == {8}
    assert result["duplicate_left"] == {3}
    assert result["duplicate_right"] == {4}
    assert result["duplicate_both"] == {5}
    assert result["inner"] == {2, 6, 7}


def test_classify_keys_row_drift_dupes_fixture(fixtures_dir):
    left = pd.read_csv(fixtures_dir / "row_drift_dupes_left.csv")
    right = pd.read_csv(fixtures_dir / "row_drift_dupes_right.csv")

    left_keys = unique_keys(left, ["id"])
    right_keys = unique_keys(right, ["id"])
    dup_left = find_duplicates(left, ["id"])
    dup_right = find_duplicates(right, ["id"])

    result = classify_keys(left_keys, right_keys, dup_left, dup_right)

    assert result["left_only"] == {("1",)}
    assert result["inner"] == {("2",), ("3",), ("4",)}
    assert result["right_only"] == {("5",), ("6",)}
    assert result["duplicate_left"] == set()
    assert result["duplicate_right"] == set()
    assert result["duplicate_both"] == set()


def test_classify_keys_duplicated_key_absent_from_other_side_stays_left_only():
    """D8 nuance: a key duplicated within left but entirely absent from right
    is 'left_only', not 'duplicate_left' -- duplicate_* only reclassifies
    keys that would otherwise be inner candidates (present on both sides)."""
    result = classify_keys(
        left_keys={1, 2},
        right_keys={2},
        dup_left_keys={1},  # id 1 duplicated in left, but not present in right at all
        dup_right_keys=set(),
    )
    assert result["left_only"] == {1}
    assert result["duplicate_left"] == set()
    assert result["inner"] == {2}


# --------------------------------------------------------------------------
# row_verdict
# --------------------------------------------------------------------------


def test_row_verdict_success_when_no_differences():
    classification = {
        "left_only": set(),
        "right_only": set(),
        "duplicate_left": set(),
        "duplicate_right": set(),
        "duplicate_both": set(),
        "inner": {1, 2, 3},
    }
    assert row_verdict(classification) == "success"


@pytest.mark.parametrize(
    "key", ["left_only", "right_only", "duplicate_left", "duplicate_right", "duplicate_both"]
)
def test_row_verdict_completed_with_differences_when_any_non_inner_bucket_populated(key):
    classification = {
        "left_only": set(),
        "right_only": set(),
        "duplicate_left": set(),
        "duplicate_right": set(),
        "duplicate_both": set(),
        "inner": {1},
    }
    classification[key] = {99}
    assert row_verdict(classification) == "completed-with-differences"


def test_row_verdict_failed_when_inner_empty_even_with_differences():
    classification = {
        "left_only": {1},
        "right_only": set(),
        "duplicate_left": set(),
        "duplicate_right": set(),
        "duplicate_both": set(),
        "inner": set(),
    }
    assert row_verdict(classification) == "failed"


def test_row_verdict_failed_when_everything_empty():
    """Inner empty with nothing else populated either -- still failed (spec:
    'failed only if inner is empty', unconditionally)."""
    classification = {
        "left_only": set(),
        "right_only": set(),
        "duplicate_left": set(),
        "duplicate_right": set(),
        "duplicate_both": set(),
        "inner": set(),
    }
    assert row_verdict(classification) == "failed"


# --------------------------------------------------------------------------
# run() -- integration over hand-built layer1/layer2 LayerResults
# --------------------------------------------------------------------------


def test_run_identical_fixture_is_success(make_config, fixtures_dir):
    layer1 = _layer1_result("identical", fixtures_dir)
    layer2 = _layer2_result(["id", "name", "value"])
    config = _config(make_config, "identical", fixtures_dir)

    result = run(layer1, layer2, config)

    assert result.name == "layer_3_compare_rows"
    assert result.verdict == "success"
    assert result.extras["summary"] == {
        "left_only": 0,
        "inner": 5,
        "right_only": 0,
        "duplicates": 0,
        "row_map": {
            "dupes_left": 0,
            "left_only": 0,
            "inner": 5,
            "right_only": 0,
            "dupes_right": 0,
            "dupes_both": 0,
        },
    }
    assert result.extras["inner_keys"] == {("1",), ("2",), ("3",), ("4",), ("5",)}
    assert list(result.data.columns) == ["id", "status"]
    assert result.data.empty


def test_run_row_drift_dupes_fixture_is_completed_with_differences(make_config, fixtures_dir):
    layer1 = _layer1_result("row_drift_dupes", fixtures_dir)
    layer2 = _layer2_result(["id", "name", "value"])
    config = _config(make_config, "row_drift_dupes", fixtures_dir)

    result = run(layer1, layer2, config)

    assert result.verdict == "completed-with-differences"
    assert result.extras["inner_keys"] == {("2",), ("3",), ("4",)}
    assert result.extras["summary"] == {
        "left_only": 1,
        "inner": 3,
        "right_only": 2,
        "duplicates": 1,  # distinct duplicated keys (id=1), not row count (2 rows)
        "row_map": {
            "dupes_left": 0,  # id=1 is duplicated in left but absent from right -> left_only, not a dupes bucket
            "left_only": 1,
            "inner": 3,
            "right_only": 2,
            "dupes_right": 0,
            "dupes_both": 0,
        },
    }

    data = result.data
    assert list(data.columns) == ["id", "status"]
    assert data["id"].tolist() == [1, 5, 6]
    assert data["status"].tolist() == ["left_only", "right_only", "right_only"]


def test_run_common_columns_unused_but_required_in_signature(make_config, fixtures_dir):
    """layer2_result.extras['common_columns'] is accepted for interface
    parity but is not consulted by row-matching logic -- an empty/wrong
    list must not change the result, only a missing key would KeyError."""
    layer1 = _layer1_result("identical", fixtures_dir)
    layer2 = _layer2_result([])  # deliberately empty/unused
    config = _config(make_config, "identical", fixtures_dir)

    result = run(layer1, layer2, config)
    assert result.verdict == "success"


def test_run_failed_when_inner_empty(make_config, tmp_path):
    """Hand-built edge case (not covered by any CSV fixture): every key
    that's present on both sides is also duplicated in left, so the inner
    set collapses to empty and the layer fails (spec step 4) even though
    left/right share the same id values."""
    df_left = pd.DataFrame(
        {"id": [1, 1, 2, 2], "name": ["A", "A", "B", "B"], "value": [10, 10, 20, 20]}
    )
    df_right = pd.DataFrame({"id": [1, 2], "name": ["A", "B"], "value": [10, 20]})

    layer1 = LayerResult(
        name="layer_1_read",
        verdict="success",
        data=pd.DataFrame(),
        extras={
            "df_left": df_left,
            "df_right": df_right,
            "left_encoding": "utf-8",
            "right_encoding": "utf-8",
            "files": {
                "left": {"path": "left.csv", "encoding": "utf-8"},
                "right": {"path": "right.csv", "encoding": "utf-8"},
            },
        },
    )
    layer2 = _layer2_result(["id", "name", "value"])
    config = type("Config", (), {"KEY_COLUMNS": ["id"]})()

    result = run(layer1, layer2, config)

    assert result.verdict == "failed"
    assert result.extras["inner_keys"] == set()
    assert result.extras["summary"]["inner"] == 0
    assert result.extras["summary"]["duplicates"] == 2  # both id 1 and id 2 duplicated in left
    # Both keys land in duplicate_left (present on both sides, dup'd in left only).
    assert set(result.data["id"].tolist()) == {1, 2}
    assert set(result.data["status"].tolist()) == {"duplicate_left"}


# --------------------------------------------------------------------------
# gate.decide
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "verdict,expected", [("success", "CONTINUE"), ("completed-with-differences", "CONTINUE"), ("failed", "STOP")]
)
def test_gate_decide(verdict, expected):
    assert decide(verdict) == expected


# --------------------------------------------------------------------------
# export() -- real CSV/TXT via ExecutionContext
# --------------------------------------------------------------------------


def test_export_writes_csv_and_txt(make_config, fixtures_dir):
    layer1 = _layer1_result("row_drift_dupes", fixtures_dir)
    layer2 = _layer2_result(["id", "name", "value"])
    config = _config(make_config, "row_drift_dupes", fixtures_dir)

    ctx = ExecutionContext.create(config, now=datetime(2026, 7, 18, 12, 0, 0))
    ctx.record(layer1)

    result = run(layer1, layer2, config)
    export(result, ctx)

    csv_path = ctx.csv_path(result.name)
    txt_path = ctx.txt_path(result.name)
    assert csv_path.exists()
    assert txt_path.exists()

    csv_df = pd.read_csv(csv_path)
    assert csv_df["status"].tolist() == ["left_only", "right_only", "right_only"]

    txt_content = txt_path.read_text(encoding="utf-8")
    assert "Layer 3 - Compare Rows" in txt_content
    assert "Verdict:    completed-with-differences" in txt_content
    assert "row_drift_dupes_left.csv" in txt_content
    assert "row_drift_dupes_right.csv" in txt_content
    assert "encoding: utf-8" in txt_content


def test_export_writes_artifacts_even_on_failed_verdict(make_config):
    """Architecture.md's layer contract: artifacts are always written before
    the gate runs, including on a failed verdict."""
    df_left = pd.DataFrame({"id": [1, 1], "name": ["A", "A"], "value": [10, 10]})
    df_right = pd.DataFrame({"id": [1], "name": ["A"], "value": [10]})
    layer1 = LayerResult(
        name="layer_1_read",
        verdict="success",
        data=pd.DataFrame(),
        extras={
            "df_left": df_left,
            "df_right": df_right,
            "left_encoding": "utf-8",
            "right_encoding": "utf-8",
            "files": {
                "left": {"path": "left.csv", "encoding": "utf-8"},
                "right": {"path": "right.csv", "encoding": "utf-8"},
            },
        },
    )
    layer2 = _layer2_result(["id", "name", "value"])
    config = make_config()
    config.KEY_COLUMNS = ["id"]

    ctx = ExecutionContext.create(config)
    ctx.record(layer1)

    result = run(layer1, layer2, config)
    assert result.verdict == "failed"

    export(result, ctx)  # must not raise, must write files despite failure
    assert ctx.csv_path(result.name).exists()
    assert ctx.txt_path(result.name).exists()

    # Gate runs only after artifacts exist.
    assert decide(result.verdict) == "STOP"


# --------------------------------------------------------------------------
# report() -- real PDF via ExecutionContext + ReportBuilder
# --------------------------------------------------------------------------


def test_report_writes_nonempty_pdf(make_config, fixtures_dir):
    layer1 = _layer1_result("row_drift_dupes", fixtures_dir)
    layer2 = _layer2_result(["id", "name", "value"])
    config = _config(make_config, "row_drift_dupes", fixtures_dir)

    ctx = ExecutionContext.create(config)
    ctx.record(layer1)

    result = run(layer1, layer2, config)
    export(result, ctx)
    report(result, ctx)

    pdf_path = ctx.pdf_path(result.name)
    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 0
    assert pdf_path.read_bytes().startswith(b"%PDF-")


def test_report_success_verdict_pdf(make_config, fixtures_dir):
    layer1 = _layer1_result("identical", fixtures_dir)
    layer2 = _layer2_result(["id", "name", "value"])
    config = _config(make_config, "identical", fixtures_dir)

    ctx = ExecutionContext.create(config)
    ctx.record(layer1)

    result = run(layer1, layer2, config)
    export(result, ctx)
    report(result, ctx)

    pdf_path = ctx.pdf_path(result.name)
    assert pdf_path.exists()
    assert pdf_path.read_bytes().startswith(b"%PDF-")
