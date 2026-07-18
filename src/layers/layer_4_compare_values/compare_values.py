"""Layer 4 -- cell-by-cell value comparison + accepted-differences policy.

Per ``.claude/layers/layer_4_compare_values.md`` and ``.claude/docs/decisions.md``
(D3, D9): over the inner rows layer 3 matched (duplicates already excluded, D8)
and the common columns layer 2 kept, compare every non-key cell and emit a
long-format diff table -- one row per differing cell. Value equality follows
the D9 matrix (NaN==NaN, numeric coercion with optional per-column tolerance,
else trailing-whitespace-stripped string equality). Each diff is then flagged
against ``config.ACCEPTED_DIFFERENCES_PATH``: a diff whose column is accepted
does not count against the verdict (D3), so the run is ``success`` when there
are no diffs *or* every diff is accepted, and ``failed`` the moment one
non-accepted diff exists. This is the terminal layer; its verdict drives exit
code 4 (D11) via ``ExecutionContext.exit_code``.

Code style (architecture.md#code-style): the comparison itself is pure --
``align_frames``, ``compare_cells``, ``flag_accepted``, ``value_verdict`` never
touch the filesystem. The only I/O is reading the accepted-differences policy
file (``load_accepted_differences``, an input load analogous to layer 1 reading
its inputs) and ``export``/``report``, which delegate all writing to
``src/utils/artifacts.py`` and ``src/utils/pdf.py``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.utils.artifacts import write_csv, write_txt
from src.utils.execution import ExecutionContext, LayerResult, Verdict
from src.utils.keys import key_frame
from src.utils.pdf import ReportBuilder, barh_chart

LAYER_NAME = "layer_4_compare_values"

_ACCEPTED_FLAG = "acceptable_difference"

#: Diff-table columns *after* the key columns (which are prepended per row).
_DIFF_TAIL_COLUMNS = ["column", "value_left", "value_right"]

#: Temporary sort column used to align both sides by composite key; unlikely
#: to collide with a real data column, and dropped before the frame is returned.
_SORT_COLUMN = "\x00_key\x00"


# --------------------------------------------------------------------------
# Value equality -- the D9 matrix (this is where subtle correctness lives)
# --------------------------------------------------------------------------


def _is_na(value: object) -> bool:
    """Missing test that never raises on array-like/odd inputs.

    ``pd.isna`` returns an array for array-likes; layer 4 only ever passes
    scalars, but the guard keeps a stray object from turning a comparison
    into a truth-value-of-an-array error.
    """
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _as_number(value: object) -> float | None:
    """Return ``value`` as a finite ``float`` when it *is* a number or a numeric
    string, else ``None`` (D9's "both sides parse as numeric" test).

    Booleans are deliberately not numbers here (``True`` must not equal ``1``),
    and non-finite results (``inf``/``nan`` from a literal string) fall back to
    string comparison so e.g. two ``"nan"`` strings compare equal instead of
    NaN-comparing unequal to themselves.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, np.integer, np.floating)):
        number = float(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
    else:
        return None
    return number if math.isfinite(number) else None


def _as_text(value: object) -> str:
    """String form for the fallback comparison, trailing whitespace stripped (D9)."""
    return ("" if value is None else str(value)).rstrip()


def values_equal(left: object, right: object, tolerance: float = 0.0) -> bool:
    """Are two cell values equal under D9?

    1. Both missing -> equal (NaN==NaN is True). Exactly one missing -> not equal.
    2. Both parse as numbers -> equal iff ``abs(left-right) <= tolerance``
       (default ``0`` = exact, so ``1 == 1.0`` but ``200 != 205``).
    3. Otherwise -> equal iff the strings match after stripping trailing
       whitespace (dates are compared as text, not format-normalized).
    """
    left_na, right_na = _is_na(left), _is_na(right)
    if left_na or right_na:
        return left_na and right_na

    left_num, right_num = _as_number(left), _as_number(right)
    if left_num is not None and right_num is not None:
        return abs(left_num - right_num) <= tolerance

    return _as_text(left) == _as_text(right)


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
    (guaranteed by layer 2's gate, D2), so both are present in the output.
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
# Accepted-differences policy file (the only input-load I/O in this module)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class AcceptedDifferences:
    """Parsed ``accepted_differences.csv`` (``column, reason, example_*``).

    ``columns`` is the ordered, de-duplicated accepted column set; ``reasons``
    maps each to its reason string (for the PDF's under-chart list and the
    dashboard popup); ``note`` is a human-readable line about where the policy
    came from -- always surfaced in the report so a missing/empty file is
    logged, per the layer spec, rather than silently meaning "nothing accepted".
    """

    columns: tuple[str, ...]
    reasons: dict[str, str]
    note: str


def load_accepted_differences(path: Any) -> AcceptedDifferences:
    """Read the accepted-differences policy; missing/empty = nothing accepted.

    Never raises: an absent, unreadable, header-only, or malformed file all
    resolve to "nothing accepted" with an explanatory ``note`` (layer spec:
    "not an error; log it in the report").
    """
    if path is None:
        return AcceptedDifferences((), {}, "No accepted-differences file configured; nothing is accepted.")

    path = Path(path)
    if not path.is_file():
        return AcceptedDifferences(
            (), {}, f"No accepted-differences file at {path.as_posix()}; nothing is accepted."
        )

    try:
        df = pd.read_csv(path)
    except (pd.errors.EmptyDataError, pd.errors.ParserError, OSError, UnicodeDecodeError):
        return AcceptedDifferences(
            (), {}, f"Accepted-differences file {path.as_posix()} is empty or unreadable; nothing is accepted."
        )

    if df.empty or "column" not in df.columns:
        return AcceptedDifferences(
            (), {}, f"Accepted-differences file {path.as_posix()} lists no accepted columns; nothing is accepted."
        )

    has_reason = "reason" in df.columns
    columns: list[str] = []
    reasons: dict[str, str] = {}
    for _, row in df.iterrows():
        raw = row["column"]
        if pd.isna(raw):
            continue
        column = str(raw).strip()
        if not column:
            continue
        if column not in reasons:
            columns.append(column)
        reason_value = row["reason"] if has_reason else None
        reasons[column] = "" if (reason_value is None or pd.isna(reason_value)) else str(reason_value).strip()

    if not columns:
        return AcceptedDifferences(
            (), {}, f"Accepted-differences file {path.as_posix()} lists no accepted columns; nothing is accepted."
        )
    return AcceptedDifferences(
        tuple(columns), reasons, f"Loaded {len(columns)} accepted column(s) from {path.as_posix()}."
    )


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


# --------------------------------------------------------------------------
# run
# --------------------------------------------------------------------------


def run(
    layer1_result: LayerResult,
    layer2_result: LayerResult,
    layer3_result: LayerResult,
    config: Any,
) -> LayerResult:
    """Compare inner rows x common columns and apply the accepted-differences policy.

    Consumes layer 1's DataFrames, layer 2's ``common_columns``, and layer 3's
    ``inner_keys`` (architecture.md's layer inputs table).
    """
    df_left: pd.DataFrame = layer1_result.extras["df_left"]
    df_right: pd.DataFrame = layer1_result.extras["df_right"]
    common_columns = list(layer2_result.extras["common_columns"])
    inner_keys: set = layer3_result.extras["inner_keys"]
    key_columns = list(config.KEY_COLUMNS)
    tolerances = dict(getattr(config, "PER_COLUMN_NUMERIC_TOLERANCE", {}) or {})

    left_aligned, right_aligned = align_frames(
        df_left, df_right, common_columns, key_columns, inner_keys
    )
    accepted = load_accepted_differences(getattr(config, "ACCEPTED_DIFFERENCES_PATH", None))

    diff_table = compare_cells(
        left_aligned, right_aligned, common_columns, key_columns, tolerances
    ).pipe(flag_accepted, accepted.columns)
    verdict = value_verdict(diff_table)

    compare_columns = [c for c in common_columns if c not in set(key_columns)]
    summary = _build_summary(diff_table, compare_columns, len(left_aligned), accepted)

    extras = {
        "summary": summary,
        "accepted": {
            "columns": list(accepted.columns),
            "reasons": accepted.reasons,
            "note": accepted.note,
        },
        "compared_columns": compare_columns,
        "key_columns": key_columns,
    }
    return LayerResult(name=LAYER_NAME, verdict=verdict, data=diff_table, extras=extras)


# --------------------------------------------------------------------------
# export / report (I/O -- the only file-writing functions in this module)
# --------------------------------------------------------------------------


def _upstream_files(ctx: ExecutionContext) -> dict[str, dict[str, Any]]:
    """Left/right path + encoding recorded by layer 1 (layer 4 never reads inputs).

    Mirrors ``ExecutionContext.manifest_dict``'s fallback so an out-of-order
    export/report never crashes when layer 1 has not been recorded yet.
    """
    layer1 = ctx.results.get("layer_1_read")
    if layer1 is not None and "files" in layer1.extras:
        return layer1.extras["files"]
    return {
        "left": {"path": str(ctx.config.INPUT_LEFT), "encoding": None},
        "right": {"path": str(ctx.config.INPUT_RIGHT), "encoding": None},
    }


def _header_lines(result: LayerResult, ctx: ExecutionContext) -> list[str]:
    """D12 header block: title, files, encodings, verdict, timestamp."""
    files = _upstream_files(ctx)
    left, right = files["left"], files["right"]
    return [
        "Layer 4 - Compare Values",
        f"Left file:  {left['path']}   (encoding: {left['encoding']})",
        f"Right file: {right['path']}   (encoding: {right['encoding']})",
        f"Verdict:    {result.verdict}",
        f"Generated:  {ctx.created_at.strftime('%Y-%m-%d %H:%M:%S')}",
    ]


def export(result: LayerResult, ctx: ExecutionContext) -> None:
    """Write ``layer_4_compare_values.csv``/``.txt`` (D12).

    Always called before the gate, including on a ``failed`` verdict
    (architecture.md's contract); never calls ``.to_csv`` directly.
    """
    write_csv(result.data, ctx.csv_path(result.name))
    write_txt(result.data, ctx.txt_path(result.name), header_lines=_header_lines(result, ctx))


def report(result: LayerResult, ctx: ExecutionContext) -> None:
    """Write ``layer_4_compare_values.pdf``: header + verdict banner + per-column
    difference-count table + horizontal bar chart (accepted columns grey, D14)
    + the accepted-difference note and reasons under the chart."""
    files = _upstream_files(ctx)
    left, right = files["left"], files["right"]

    builder = ReportBuilder(
        title="Layer 4 - Compare Values",
        left_file=str(left["path"]),
        right_file=str(right["path"]),
        left_encoding=str(left["encoding"] or "unknown"),
        right_encoding=str(right["encoding"] or "unknown"),
        verdict=result.verdict,
        timestamp=ctx.created_at,
    )

    summary = result.extras.get("summary", {})
    diff_counts: dict[str, int] = summary.get("diff_counts", {})
    accepted_set = set(summary.get("accepted_columns", []))

    labels = list(diff_counts.keys())
    values = [diff_counts[c] for c in labels]
    grey_mask = [c in accepted_set for c in labels]

    # Per-column difference counts table.
    if labels:
        table_df = pd.DataFrame(
            {
                "column": labels,
                "differences": values,
                "accepted": grey_mask,
            }
        )
        builder.add_table(table_df, heading="Per-column difference counts")
    else:
        builder.add_heading("Per-column difference counts")
        builder.add_paragraph("No value differences across the compared cells.")

    # Horizontal bar chart (D14): accepted columns grey, others in the alert color.
    if labels:
        has_accepted = any(grey_mask)
        has_non_accepted = not all(grey_mask)
        fig = barh_chart(
            labels,
            values,
            grey_mask,
            title="Differences per column",
            xlabel="Difference count",
            series_label="Not accepted" if has_non_accepted else None,
            grey_label="Accepted" if has_accepted else None,
        )
        builder.add_chart(fig)

    # Accepted-differences note (logs a missing/empty policy file) + reasons.
    accepted = result.extras.get("accepted", {})
    note = accepted.get("note")
    if note:
        builder.add_paragraph(note)

    reasons: dict[str, str] = accepted.get("reasons", {})
    accepted_with_diffs = [c for c in labels if c in accepted_set]
    if accepted_with_diffs:
        builder.add_heading("Accepted differences")
        for col in accepted_with_diffs:
            reason = reasons.get(col) or "(no reason given)"
            builder.add_paragraph(f"{col}: {reason}")

    builder.output(str(ctx.pdf_path(result.name)))
