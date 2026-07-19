"""Layer 2 pure logic -- compare column sets and dtypes.

Pure computation over the two DataFrames layer 1 produced (spec:
``split_columns``, ``dtype_table``, ``column_verdict``, plus the export-table
assembly). No I/O -- ``run`` lives in ``run.py`` and file writing in
``output.py`` (.claude/layers/layer_2_compare_columns.md).
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from src.utils.execution import Verdict

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
