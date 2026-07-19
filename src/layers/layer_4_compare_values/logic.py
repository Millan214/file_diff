"""Layer 4 pure logic -- align rows, diff cells, flag accepted, decide verdict.

Per ``.claude/layers/layer_4_compare_values.md`` and ``.claude/docs/decisions.md``
(D3, D9): over the inner rows layer 3 matched (duplicates already excluded, D8)
and the common columns layer 2 kept, compare every non-key cell and emit a
long-format diff table -- one row per differing cell. Cell equality is
delegated to ``equality.values_equal`` (the D9 matrix); the accepted-difference
policy is loaded by ``accepted.py``. Each diff is flagged against the accepted
set, and the verdict is ``success`` when there are no diffs *or* every diff is
accepted (D3), else ``failed``.

Pure computation only (architecture.md#code-style) -- ``run`` lives in
``run.py`` and file writing in ``output.py``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pandas as pd

from src.utils.execution import Verdict
from src.utils.keys import key_frame

from .accepted import AcceptedDifferences
from .equality import values_equal

LAYER_NAME = "layer_4_compare_values"

_ACCEPTED_FLAG = "acceptable_difference"

#: Diff-table columns *after* the key columns (which are prepended per row).
_DIFF_TAIL_COLUMNS = ["column", "value_left", "value_right"]

#: Temporary sort column used to align both sides by composite key; unlikely
#: to collide with a real data column, and dropped before the frame is returned.
_SORT_COLUMN = "\x00_key\x00"


# --------------------------------------------------------------------------
# Pure transformations: align_frames, compare_cells, flag_accepted, value_verdict
# --------------------------------------------------------------------------


def _restrict_and_sort(
    df: pd.DataFrame,
    common_columns: Sequence[str],
    key_columns: Sequence[str],
    inner_keys: set,
) -> pd.DataFrame:
    """One side of ``align_frames``: keep inner rows, keep common columns, sort by key.

    Inner keys exclude anything duplicated on either side (D8), so each key
    appears exactly once here -- sorting both sides by the same composite key
    is enough to line row ``i`` of left up with row ``i`` of right.
    """
    kf = key_frame(df, key_columns)
    mask = kf.isin(inner_keys)
    subset = df.loc[mask, list(common_columns)].copy()
    subset[_SORT_COLUMN] = kf[mask]
    subset = subset.sort_values(_SORT_COLUMN, kind="stable").drop(columns=_SORT_COLUMN)
    return subset.reset_index(drop=True)


def align_frames(
    df_left: pd.DataFrame,
    df_right: pd.DataFrame,
    common_columns: Sequence[str],
    key_columns: Sequence[str],
    inner_keys: set,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Filter both frames to ``inner_keys``, project to ``common_columns``, sort by key.

    Returns ``(left_aligned, right_aligned)`` with a fresh 0..n-1 index each,
    row-aligned so that position ``i`` refers to the same key on both sides
    (layer spec step 1). ``key_columns`` are a subset of ``common_columns``
    (guaranteed by layer 2, D2), so both are present in the output.
    """
    left_aligned = _restrict_and_sort(df_left, common_columns, key_columns, inner_keys)
    right_aligned = _restrict_and_sort(df_right, common_columns, key_columns, inner_keys)
    return left_aligned, right_aligned


def compare_cells(
    left_aligned: pd.DataFrame,
    right_aligned: pd.DataFrame,
    common_columns: Sequence[str],
    key_columns: Sequence[str],
    tolerances: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Long-format diff table: one row per differing cell (layer spec steps 2-3).

    Compares every *non-key* common column (key columns are the row identity --
    equal by construction, never data to diff). Row-major, so all differences
    for one key are grouped together and the whole table is ordered by key.
    Columns: ``<key columns...>, column, value_left, value_right``.
    """
    tolerances = tolerances or {}
    key_columns = list(key_columns)
    key_set = set(key_columns)
    compare_columns = [c for c in common_columns if c not in key_set]
    col_tol = {c: float(tolerances.get(c, 0.0)) for c in compare_columns}

    # .tolist() drops numpy scalar wrappers so values_equal and the exported
    # cells see plain Python int/float/str/NaN.
    key_values = {k: left_aligned[k].tolist() for k in key_columns}
    left_values = {c: left_aligned[c].tolist() for c in compare_columns}
    right_values = {c: right_aligned[c].tolist() for c in compare_columns}

    records: list[dict[str, Any]] = []
    for pos in range(len(left_aligned)):
        for col in compare_columns:
            left_val = left_values[col][pos]
            right_val = right_values[col][pos]
            if values_equal(left_val, right_val, col_tol[col]):
                continue
            record = {k: key_values[k][pos] for k in key_columns}
            record["column"] = col
            record["value_left"] = left_val
            record["value_right"] = right_val
            records.append(record)

    columns = [*key_columns, *_DIFF_TAIL_COLUMNS]
    if not records:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame.from_records(records, columns=columns)


def flag_accepted(diff_table: pd.DataFrame, accepted_columns: Sequence[str]) -> pd.DataFrame:
    """Append ``acceptable_difference`` = column is in the accepted set (spec step 4)."""
    accepted = set(accepted_columns)
    result = diff_table.copy()
    if result.empty:
        result[_ACCEPTED_FLAG] = pd.Series(dtype=bool)
    else:
        result[_ACCEPTED_FLAG] = [col in accepted for col in result["column"]]
    return result


def value_verdict(diff_table: pd.DataFrame) -> Verdict:
    """``success`` if no diffs or every diff is accepted (D3); else ``failed``.

    Layer 4 never returns ``completed-with-differences`` -- accepted-only diffs
    are a green pass (D3), and any non-accepted diff is a hard ``failed`` (the
    two frames are not equal), which becomes exit code 4 (D11).
    """
    if diff_table.empty:
        return "success"
    return "success" if bool(diff_table[_ACCEPTED_FLAG].all()) else "failed"


# --------------------------------------------------------------------------
# Summary assembly (dashboard.md's manifest contract + PDF chart source)
# --------------------------------------------------------------------------


def _diff_counts(diff_table: pd.DataFrame, compare_columns: Sequence[str]) -> dict[str, int]:
    """``{column: diff count}`` for columns that have >=1 difference, in
    ``compare_columns`` (= left-file/common) order -- the bar-chart source for
    both the PDF and the dashboard (dashboard.md's ``summary.diff_counts``).
    """
    if diff_table.empty:
        return {}
    counts = diff_table["column"].value_counts()
    return {col: int(counts[col]) for col in compare_columns if col in counts.index}


def _build_summary(
    diff_table: pd.DataFrame,
    compare_columns: Sequence[str],
    compared_rows: int,
    accepted: AcceptedDifferences,
) -> dict[str, Any]:
    """Verbatim-copied into ``manifest["layers"]["layer_4..."]["summary"]``.

    ``diff_counts`` + ``accepted_columns`` are the dashboard contract
    (dashboard.md); the totals are convenience figures for the PDF/dashboard
    headline.
    """
    accepted_mask = diff_table[_ACCEPTED_FLAG] if not diff_table.empty else pd.Series(dtype=bool)
    accepted_count = int(accepted_mask.sum()) if not diff_table.empty else 0
    total = int(len(diff_table))
    return {
        "diff_counts": _diff_counts(diff_table, compare_columns),
        "accepted_columns": list(accepted.columns),
        "compared_rows": int(compared_rows),
        "compared_columns": len(list(compare_columns)),
        "total_differences": total,
        "accepted_differences": accepted_count,
        "non_accepted_differences": total - accepted_count,
    }
