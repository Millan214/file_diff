"""Layer 2 -- compare column sets and dtypes (.claude/layers/layer_2_compare_columns.md).

``run`` is pure computation over the two DataFrames layer 1 produced; the
only I/O in this module lives in ``export``/``report``, which delegate all
file writing to ``src/utils/artifacts.py`` and ``src/utils/pdf.py``
(architecture.md's layer contract -- artifacts are always written before the
gate runs, even on a ``failed`` verdict).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pandas as pd

from src.utils.artifacts import write_csv, write_txt
from src.utils.execution import ExecutionContext, LayerResult, Verdict
from src.utils.pdf import ReportBuilder

LAYER_NAME = "layer_2_compare_columns"

_REPORT_COLUMNS = [
    "column",
    "in_left",
    "in_right",
    "dtype_left",
    "dtype_right",
    "dtype_match",
    "status",
]


# --------------------------------------------------------------------------
# Pure transformations (spec: split_columns, dtype_table, column_verdict)
# --------------------------------------------------------------------------


def split_columns(df_left: pd.DataFrame, df_right: pd.DataFrame) -> dict[str, list[str]]:
    """Left-only / right-only / common column names.

    ``common`` is the ordered intersection, ordered by ``df_left``'s column
    order (layer 2 spec, step 1).
    """
    left_cols = list(df_left.columns)
    right_cols = list(df_right.columns)
    left_set, right_set = set(left_cols), set(right_cols)

    return {
        "left_only": [c for c in left_cols if c not in right_set],
        "right_only": [c for c in right_cols if c not in left_set],
        "common": [c for c in left_cols if c in right_set],
    }


def dtype_table(
    df_left: pd.DataFrame, df_right: pd.DataFrame, common: Sequence[str]
) -> pd.DataFrame:
    """``column, dtype_left, dtype_right, dtype_match`` for the common columns.

    Mismatches are informational only (D7) -- they never affect the verdict
    beyond downgrading ``success`` to ``completed-with-differences``.
    """
    common = list(common)
    dtype_left = [str(df_left[c].dtype) for c in common]
    dtype_right = [str(df_right[c].dtype) for c in common]
    return pd.DataFrame(
        {
            "column": common,
            "dtype_left": dtype_left,
            "dtype_right": dtype_right,
            "dtype_match": [l == r for l, r in zip(dtype_left, dtype_right)],
        }
    )


def column_verdict(
    cols: dict[str, list[str]], dtypes: pd.DataFrame, key_columns: Sequence[str]
) -> Verdict:
    """success / completed-with-differences / failed (D2, D5, D7).

    ``failed`` when no key columns are configured, the common set is empty, or
    any configured key column (D2) is missing from it -- layer 3 could not
    build row keys in any of those cases. Failing here (a clean STOP, exit 2)
    keeps a mis-authored config from crashing layers 3/4, which read
    ``config.KEY_COLUMNS`` directly.
    """
    if not key_columns or not cols["common"] or any(k not in cols["common"] for k in key_columns):
        return "failed"
    if cols["left_only"] or cols["right_only"] or not bool(dtypes["dtype_match"].all()):
        return "completed-with-differences"
    return "success"


# --------------------------------------------------------------------------
# Report table assembly (union of left/right columns, chained with .pipe)
# --------------------------------------------------------------------------


def _union_rows(
    df_left: pd.DataFrame, df_right: pd.DataFrame, cols: dict[str, list[str]]
) -> pd.DataFrame:
    """One row per column across the union, raw dtypes, no status yet.

    Ordered by ``df_left``'s column order (covering both common and
    left_only columns, since together they are exactly ``df_left.columns``)
    followed by the right_only columns in ``df_right``'s order.
    """
    ordered_columns = list(df_left.columns) + cols["right_only"]
    left_set, right_set = set(df_left.columns), set(df_right.columns)
    return pd.DataFrame(
        {
            "column": ordered_columns,
            "in_left": [c in left_set for c in ordered_columns],
            "in_right": [c in right_set for c in ordered_columns],
            "dtype_left": [
                str(df_left[c].dtype) if c in left_set else None for c in ordered_columns
            ],
            "dtype_right": [
                str(df_right[c].dtype) if c in right_set else None for c in ordered_columns
            ],
        }
    )


def _add_dtype_match(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["dtype_match"] = (df["in_left"] & df["in_right"]) & (
        df["dtype_left"] == df["dtype_right"]
    )
    return df


def _add_status(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["status"] = [
        "common" if in_l and in_r else ("left_only" if in_l else "right_only")
        for in_l, in_r in zip(df["in_left"], df["in_right"])
    ]
    return df


def build_column_report(
    df_left: pd.DataFrame, df_right: pd.DataFrame, cols: dict[str, list[str]]
) -> pd.DataFrame:
    """Full export table: one row per column across the union (spec's Exports
    section) -- ``column, in_left, in_right, dtype_left, dtype_right,
    dtype_match, status``.
    """
    return (
        _union_rows(df_left, df_right, cols)
        .pipe(_add_dtype_match)
        .pipe(_add_status)
        [_REPORT_COLUMNS]
    )


# --------------------------------------------------------------------------
# run
# --------------------------------------------------------------------------


def run(layer1_result: LayerResult, config: Any) -> LayerResult:
    """Compare layer 1's two DataFrames' column sets and dtypes."""
    df_left: pd.DataFrame = layer1_result.extras["df_left"]
    df_right: pd.DataFrame = layer1_result.extras["df_right"]
    key_columns = list(getattr(config, "KEY_COLUMNS", []))

    cols = split_columns(df_left, df_right)
    dtypes = dtype_table(df_left, df_right, cols["common"])
    verdict = column_verdict(cols, dtypes, key_columns)
    data = build_column_report(df_left, df_right, cols)

    dtype_mismatches = int((~dtypes["dtype_match"]).sum()) if not dtypes.empty else 0
    summary = {
        "left_only": len(cols["left_only"]),
        "right_only": len(cols["right_only"]),
        "common": len(cols["common"]),
        "dtype_mismatches": dtype_mismatches,
    }

    extras = {
        "common_columns": cols["common"],
        "left_only_columns": cols["left_only"],
        "right_only_columns": cols["right_only"],
        "dtype_table": dtypes,
        "summary": summary,
    }

    return LayerResult(name=LAYER_NAME, verdict=verdict, data=data, extras=extras)


# --------------------------------------------------------------------------
# export / report (I/O -- the only place this module touches the filesystem)
# --------------------------------------------------------------------------


def _upstream_files(ctx: ExecutionContext) -> dict[str, dict[str, Any]]:
    """Left/right file path + encoding recorded by layer 1.

    Layer 2 itself never reads the input files, so it pulls this from layer
    1's recorded ``LayerResult`` on the context (mirrors
    ``ExecutionContext.manifest_dict``'s own fallback for the same reason).
    """
    layer1 = ctx.results.get("layer_1_read")
    if layer1 is not None and "files" in layer1.extras:
        return layer1.extras["files"]
    return {
        "left": {"path": str(ctx.config.INPUT_LEFT), "encoding": None},
        "right": {"path": str(ctx.config.INPUT_RIGHT), "encoding": None},
    }


def _header_lines(result: LayerResult, ctx: ExecutionContext) -> list[str]:
    """D12 header block: files, encodings, verdict, timestamp."""
    files = _upstream_files(ctx)
    left, right = files["left"], files["right"]
    return [
        f"Left file:  {left['path']}   (encoding: {left['encoding']})",
        f"Right file: {right['path']}   (encoding: {right['encoding']})",
        f"Verdict:    {result.verdict}",
        f"Generated:  {ctx.created_at.strftime('%Y-%m-%d %H:%M:%S')}",
    ]


def export(result: LayerResult, ctx: ExecutionContext) -> None:
    """Write ``layer_2_compare_columns.csv``/``.txt`` from ``result.data``."""
    write_csv(result.data, ctx.csv_path(result.name))
    write_txt(
        result.data,
        ctx.txt_path(result.name),
        header_lines=_header_lines(result, ctx),
    )


def report(result: LayerResult, ctx: ExecutionContext) -> None:
    """Write ``layer_2_compare_columns.pdf``: header + banner + three tables
    (left_only, right_only, common-with-dtypes) + the common-columns list
    layer 3 continues with.
    """
    files = _upstream_files(ctx)
    left, right = files["left"], files["right"]

    builder = ReportBuilder(
        title="Layer 2 -- Compare Columns",
        left_file=str(left["path"]),
        right_file=str(right["path"]),
        left_encoding=str(left["encoding"] or "unknown"),
        right_encoding=str(right["encoding"] or "unknown"),
        verdict=result.verdict,
        timestamp=ctx.created_at,
    )

    data = result.data
    left_only_df = data.loc[data["status"] == "left_only", ["column", "dtype_left"]]
    right_only_df = data.loc[data["status"] == "right_only", ["column", "dtype_right"]]
    common_df = data.loc[
        data["status"] == "common", ["column", "dtype_left", "dtype_right", "dtype_match"]
    ]

    builder.add_table(left_only_df, heading="Left-only columns")
    builder.add_table(right_only_df, heading="Right-only columns")
    builder.add_table(common_df, heading="Common columns (dtypes)")

    common_columns = result.extras.get("common_columns", [])
    builder.add_heading("Common columns carried forward to layer 3")
    builder.add_paragraph(", ".join(common_columns) if common_columns else "(none)")

    builder.output(str(ctx.pdf_path(result.name)))
