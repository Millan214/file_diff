"""Tests for src/layers/layer_2_compare_columns/ (compare_columns.py + gate.py).

Layer 1 does not exist in this worktree yet -- per the cross-layer interface
contract, ``LayerResult``s that stand in for layer 1's output are built by
hand here (loading the fixture CSVs directly with ``pd.read_csv``) rather
than by calling layer 1's code.
"""

from __future__ import annotations

import types
from pathlib import Path

import pandas as pd
import pytest

from src.layers.layer_2_compare_columns import compare_columns, gate
from src.utils.execution import ExecutionContext, LayerResult

LAYER_NAME = "layer_2_compare_columns"


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _load_pair(fixtures_dir: Path, pair: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    df_left = pd.read_csv(fixtures_dir / f"{pair}_left.csv")
    df_right = pd.read_csv(fixtures_dir / f"{pair}_right.csv")
    return df_left, df_right


def _layer1_result(
    fixtures_dir: Path, pair: str, *, left_encoding: str = "utf-8", right_encoding: str = "utf-8"
) -> LayerResult:
    """Hand-build a layer 1 LayerResult matching the fixed interface contract."""
    df_left, df_right = _load_pair(fixtures_dir, pair)
    left_path = str(fixtures_dir / f"{pair}_left.csv")
    right_path = str(fixtures_dir / f"{pair}_right.csv")
    return LayerResult(
        name="layer_1_read",
        verdict="success",
        data=df_left,
        extras={
            "df_left": df_left,
            "df_right": df_right,
            "left_encoding": left_encoding,
            "right_encoding": right_encoding,
            "files": {
                "left": {"path": left_path, "encoding": left_encoding},
                "right": {"path": right_path, "encoding": right_encoding},
            },
        },
    )


def _config(key_columns: list[str]) -> types.SimpleNamespace:
    return types.SimpleNamespace(KEY_COLUMNS=key_columns)


# --------------------------------------------------------------------------
# split_columns
# --------------------------------------------------------------------------


def test_split_columns_identical(fixtures_dir):
    df_left, df_right = _load_pair(fixtures_dir, "identical")
    cols = compare_columns.split_columns(df_left, df_right)
    assert cols == {"left_only": [], "right_only": [], "common": ["id", "name", "value"]}


def test_split_columns_drift(fixtures_dir):
    df_left, df_right = _load_pair(fixtures_dir, "column_drift")
    cols = compare_columns.split_columns(df_left, df_right)
    assert cols["common"] == ["id", "name", "value"]
    assert cols["left_only"] == ["status"]
    assert cols["right_only"] == ["department"]


def test_split_columns_ordered_by_left_file_order():
    df_left = pd.DataFrame(columns=["z", "a", "id"])
    df_right = pd.DataFrame(columns=["id", "a", "z", "extra"])
    cols = compare_columns.split_columns(df_left, df_right)
    # common must follow df_left's column order, not df_right's or alpha order.
    assert cols["common"] == ["z", "a", "id"]
    assert cols["right_only"] == ["extra"]


def test_split_columns_empty_common(fixtures_dir):
    df_left, df_right = _load_pair(fixtures_dir, "empty_common")
    cols = compare_columns.split_columns(df_left, df_right)
    assert cols["common"] == []
    assert cols["left_only"] == ["col_a", "col_b", "col_c"]
    assert cols["right_only"] == ["col_d", "col_e", "col_f"]


# --------------------------------------------------------------------------
# dtype_table
# --------------------------------------------------------------------------


def test_dtype_table_all_match(fixtures_dir):
    df_left, df_right = _load_pair(fixtures_dir, "identical")
    common = ["id", "name", "value"]
    dtypes = compare_columns.dtype_table(df_left, df_right, common)
    assert list(dtypes["column"]) == common
    assert dtypes["dtype_match"].all()


def test_dtype_table_detects_mismatch():
    df_left = pd.DataFrame({"id": [1, 2], "amount": [1, 2]})
    df_right = pd.DataFrame({"id": [1, 2], "amount": [1.5, 2.5]})
    dtypes = compare_columns.dtype_table(df_left, df_right, ["id", "amount"])
    row = dtypes.set_index("column").loc["amount"]
    assert row["dtype_left"] == "int64"
    assert row["dtype_right"] == "float64"
    assert row["dtype_match"] == False  # noqa: E712


def test_dtype_table_empty_common_yields_empty_frame():
    df_left = pd.DataFrame({"a": [1]})
    df_right = pd.DataFrame({"b": [1]})
    dtypes = compare_columns.dtype_table(df_left, df_right, [])
    assert dtypes.empty
    assert list(dtypes.columns) == ["column", "dtype_left", "dtype_right", "dtype_match"]


# --------------------------------------------------------------------------
# column_verdict
# --------------------------------------------------------------------------


def test_column_verdict_success_when_sets_and_dtypes_match(fixtures_dir):
    df_left, df_right = _load_pair(fixtures_dir, "identical")
    cols = compare_columns.split_columns(df_left, df_right)
    dtypes = compare_columns.dtype_table(df_left, df_right, cols["common"])
    verdict = compare_columns.column_verdict(cols, dtypes, ["id"])
    assert verdict == "success"


def test_column_verdict_differences_when_sets_differ(fixtures_dir):
    df_left, df_right = _load_pair(fixtures_dir, "column_drift")
    cols = compare_columns.split_columns(df_left, df_right)
    dtypes = compare_columns.dtype_table(df_left, df_right, cols["common"])
    verdict = compare_columns.column_verdict(cols, dtypes, ["id"])
    assert verdict == "completed-with-differences"


def test_column_verdict_differences_when_only_dtype_mismatches():
    df_left = pd.DataFrame({"id": [1, 2], "amount": [1, 2]})
    df_right = pd.DataFrame({"id": [1, 2], "amount": [1.5, 2.5]})
    cols = compare_columns.split_columns(df_left, df_right)
    dtypes = compare_columns.dtype_table(df_left, df_right, cols["common"])
    verdict = compare_columns.column_verdict(cols, dtypes, ["id"])
    assert verdict == "completed-with-differences"
    assert cols["left_only"] == [] and cols["right_only"] == []


def test_column_verdict_failed_when_common_empty(fixtures_dir):
    df_left, df_right = _load_pair(fixtures_dir, "empty_common")
    cols = compare_columns.split_columns(df_left, df_right)
    dtypes = compare_columns.dtype_table(df_left, df_right, cols["common"])
    verdict = compare_columns.column_verdict(cols, dtypes, ["id"])
    assert verdict == "failed"


def test_column_verdict_failed_when_key_column_missing_from_common():
    """Common set is non-empty but doesn't contain a configured key column (D2)."""
    df_left = pd.DataFrame({"name": ["a"], "value": [1]})
    df_right = pd.DataFrame({"name": ["a"], "value": [1]})
    cols = compare_columns.split_columns(df_left, df_right)
    dtypes = compare_columns.dtype_table(df_left, df_right, cols["common"])
    verdict = compare_columns.column_verdict(cols, dtypes, ["id"])
    assert verdict == "failed"


# --------------------------------------------------------------------------
# build_column_report
# --------------------------------------------------------------------------


def test_build_column_report_shape_and_status(fixtures_dir):
    df_left, df_right = _load_pair(fixtures_dir, "column_drift")
    cols = compare_columns.split_columns(df_left, df_right)
    report_df = compare_columns.build_column_report(df_left, df_right, cols)

    assert list(report_df.columns) == [
        "column", "in_left", "in_right", "dtype_left", "dtype_right", "dtype_match", "status",
    ]
    # One row per column across the union: id, name, value, status, department.
    assert len(report_df) == 5
    assert set(report_df["column"]) == {"id", "name", "value", "status", "department"}

    by_col = report_df.set_index("column")
    assert by_col.loc["id", "status"] == "common"
    assert by_col.loc["status", "status"] == "left_only"
    assert by_col.loc["status", "in_right"] == False  # noqa: E712
    assert by_col.loc["department", "status"] == "right_only"
    assert by_col.loc["department", "in_left"] == False  # noqa: E712


def test_build_column_report_left_only_columns_have_no_right_dtype(fixtures_dir):
    df_left, df_right = _load_pair(fixtures_dir, "column_drift")
    cols = compare_columns.split_columns(df_left, df_right)
    report_df = compare_columns.build_column_report(df_left, df_right, cols)
    row = report_df.set_index("column").loc["status"]
    assert pd.isna(row["dtype_right"])
    assert row["dtype_match"] == False  # noqa: E712


def test_build_column_report_row_order_follows_left_then_right_only():
    df_left = pd.DataFrame(columns=["z", "a", "id"])
    df_right = pd.DataFrame(columns=["id", "a", "z", "extra"])
    cols = compare_columns.split_columns(df_left, df_right)
    report_df = compare_columns.build_column_report(df_left, df_right, cols)
    assert list(report_df["column"]) == ["z", "a", "id", "extra"]


# --------------------------------------------------------------------------
# run() -- full layer, fixture-pair driven
# --------------------------------------------------------------------------


def test_run_identical_is_success(fixtures_dir):
    layer1 = _layer1_result(fixtures_dir, "identical")
    result = compare_columns.run(layer1, _config(["id"]))

    assert result.name == LAYER_NAME
    assert result.verdict == "success"
    assert result.extras["common_columns"] == ["id", "name", "value"]
    assert result.extras["summary"] == {
        "left_only": 0, "right_only": 0, "common": 3, "dtype_mismatches": 0,
    }
    assert len(result.data) == 3


def test_run_column_drift_is_completed_with_differences(fixtures_dir):
    layer1 = _layer1_result(fixtures_dir, "column_drift")
    result = compare_columns.run(layer1, _config(["id"]))

    assert result.verdict == "completed-with-differences"
    assert result.extras["common_columns"] == ["id", "name", "value"]
    assert result.extras["summary"]["left_only"] == 1
    assert result.extras["summary"]["right_only"] == 1
    assert result.extras["summary"]["common"] == 3
    assert len(result.data) == 5


def test_run_empty_common_is_failed(fixtures_dir):
    layer1 = _layer1_result(fixtures_dir, "empty_common")
    result = compare_columns.run(layer1, _config(["id"]))

    assert result.verdict == "failed"
    assert result.extras["common_columns"] == []
    assert result.extras["summary"]["common"] == 0
    # data is still produced (artifacts are always written, even on failure).
    assert len(result.data) == 6


# --------------------------------------------------------------------------
# gate
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "verdict,expected",
    [
        ("success", "CONTINUE"),
        ("completed-with-differences", "CONTINUE"),
        ("failed", "STOP"),
    ],
)
def test_gate_decide(verdict, expected):
    assert gate.decide(verdict) == expected


# --------------------------------------------------------------------------
# export / report -- real files via ExecutionContext
# --------------------------------------------------------------------------


@pytest.mark.parametrize("pair", ["identical", "column_drift", "empty_common"])
def test_export_writes_csv_and_txt(make_config, fixtures_dir, pair):
    layer1 = _layer1_result(fixtures_dir, pair)
    config = make_config()
    config.KEY_COLUMNS = ["id"]
    ctx = ExecutionContext.create(config)
    ctx.record(layer1)

    result = compare_columns.run(layer1, config)
    ctx.record(result)
    compare_columns.export(result, ctx)

    csv_path = ctx.csv_path(result.name)
    txt_path = ctx.txt_path(result.name)
    assert csv_path.exists() and csv_path.stat().st_size > 0
    assert txt_path.exists() and txt_path.stat().st_size > 0

    csv_content = csv_path.read_text(encoding="utf-8")
    assert "column" in csv_content and "status" in csv_content

    txt_content = txt_path.read_text(encoding="utf-8")
    assert "Verdict:" in txt_content
    assert result.verdict in txt_content


@pytest.mark.parametrize(
    "pair,expected_verdict",
    [
        ("identical", "success"),
        ("column_drift", "completed-with-differences"),
        ("empty_common", "failed"),
    ],
)
def test_report_writes_pdf_even_on_failure(make_config, fixtures_dir, pair, expected_verdict):
    """Artifacts (incl. the PDF) must be written before the gate runs, on
    every verdict including 'failed' (architecture.md's layer contract)."""
    layer1 = _layer1_result(fixtures_dir, pair)
    config = make_config()
    config.KEY_COLUMNS = ["id"]
    ctx = ExecutionContext.create(config)
    ctx.record(layer1)

    result = compare_columns.run(layer1, config)
    assert result.verdict == expected_verdict
    ctx.record(result)

    compare_columns.export(result, ctx)
    compare_columns.report(result, ctx)

    pdf_path = ctx.pdf_path(result.name)
    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 0
    assert pdf_path.read_bytes().startswith(b"%PDF-")

    # Gate decision happens after artifacts exist either way.
    decision = gate.decide(result.verdict)
    assert decision == ("STOP" if expected_verdict == "failed" else "CONTINUE")


def test_report_falls_back_to_config_paths_when_layer1_not_recorded(make_config, fixtures_dir):
    """report() must not crash if, in isolation, layer 1's result was never
    recorded on the context (mirrors ExecutionContext.manifest_dict's own
    fallback)."""
    layer1 = _layer1_result(fixtures_dir, "identical")
    config = make_config(
        left=fixtures_dir / "identical_left.csv", right=fixtures_dir / "identical_right.csv"
    )
    config.KEY_COLUMNS = ["id"]
    ctx = ExecutionContext.create(config)
    # Deliberately do NOT ctx.record(layer1).

    result = compare_columns.run(layer1, config)
    compare_columns.export(result, ctx)
    compare_columns.report(result, ctx)

    assert ctx.pdf_path(result.name).exists()
    assert ctx.csv_path(result.name).exists()
