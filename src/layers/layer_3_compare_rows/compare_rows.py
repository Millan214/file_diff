"""Layer 3 -- match rows by key and find duplicates.

Per ``.claude/layers/layer_3_compare_rows.md`` and ``.claude/docs/decisions.md``
(D1, D2, D8): classify each composite key (``config.KEY_COLUMNS``, D2) present
in ``df_left`` and/or ``df_right`` into left_only / right_only / duplicate_left
/ duplicate_right / duplicate_both / inner, where "inner" excludes any key
duplicated on either side (D8) so layer 4 never has to pick among ambiguous
pairings. The pipeline always CONTINUEs past differences here (D1) -- `failed`
is reserved for the case where nothing is left to compare at all.

Business logic below never touches the filesystem (architecture.md's
code-style rule); ``export``/``report`` are the only functions here that do
I/O, and both are thin wrappers around ``src/utils/artifacts.py`` and
``src/utils/pdf.py``.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.utils.artifacts import write_csv, write_txt
from src.utils.execution import ExecutionContext, LayerResult, Verdict
from src.utils.keys import duplicate_mask, key_frame, unique_keys
from src.utils.pdf import ReportBuilder, set_partition_chart

_STATUS_COLUMN = "status"

_LEFT_ONLY = "left_only"
_RIGHT_ONLY = "right_only"
_DUPLICATE_LEFT = "duplicate_left"
_DUPLICATE_RIGHT = "duplicate_right"
_DUPLICATE_BOTH = "duplicate_both"
_INNER = "inner"

#: Export/summary category order (excludes "inner" -- only non-inner keys
#: are exported per the layer spec).
_NON_INNER_STATUSES = (_LEFT_ONLY, _RIGHT_ONLY, _DUPLICATE_LEFT, _DUPLICATE_RIGHT, _DUPLICATE_BOTH)


# --------------------------------------------------------------------------
# Pure functions (spec's decomposition): find_duplicates, classify_keys,
# row_verdict -- built on top of src/utils/keys.py so layers 3 and 4 can
# never drift apart on pairing semantics.
# --------------------------------------------------------------------------


def find_duplicates(df: pd.DataFrame, key_columns: list[str]) -> set:
    """Distinct composite keys appearing more than once in ``df`` (spec step 1).

    Built on ``keys.key_frame``/``keys.duplicate_mask`` rather than
    reimplementing duplicate detection.
    """
    keys = key_frame(df, key_columns)
    mask = duplicate_mask(df, key_columns)
    return set(keys[mask])


def classify_keys(
    left_keys: set,
    right_keys: set,
    dup_left_keys: set,
    dup_right_keys: set,
) -> dict[str, set]:
    """Outer-merge the two key sets (spec step 2) into six disjoint buckets.

    Keys present on both sides ("both") are ``inner`` unless duplicated on
    either side (D8), in which case they get a ``duplicate_left`` /
    ``duplicate_right`` / ``duplicate_both`` status instead. A key absent
    from one side entirely keeps its ``left_only``/``right_only`` status
    even if it is *also* duplicated within its own file (e.g. the
    row_drift_dupes fixture's id=1: duplicated in left, absent from right
    -> ``left_only``, not ``duplicate_left`` -- duplication only reclassifies
    keys that would otherwise have been inner candidates).
    """
    both = left_keys & right_keys
    left_only = left_keys - right_keys
    right_only = right_keys - left_keys

    duplicate_both = both & dup_left_keys & dup_right_keys
    duplicate_left = (both & dup_left_keys) - dup_right_keys
    duplicate_right = (both & dup_right_keys) - dup_left_keys
    inner = both - dup_left_keys - dup_right_keys

    return {
        _LEFT_ONLY: left_only,
        _RIGHT_ONLY: right_only,
        _DUPLICATE_LEFT: duplicate_left,
        _DUPLICATE_RIGHT: duplicate_right,
        _DUPLICATE_BOTH: duplicate_both,
        _INNER: inner,
    }


def row_verdict(classification: dict[str, set]) -> Verdict:
    """success | completed-with-differences | failed (spec step 4).

    ``failed`` only when the inner set is empty -- there would be nothing
    left for layer 4 to compare. Otherwise any left_only/right_only/
    duplicate_* keys make it ``completed-with-differences``; none of those
    makes it ``success``. Per D1, the gate CONTINUEs past
    ``completed-with-differences`` -- only ``failed`` stops the pipeline.
    """
    if not classification[_INNER]:
        return "failed"
    has_differences = any(classification[status] for status in _NON_INNER_STATUSES)
    return "completed-with-differences" if has_differences else "success"


# --------------------------------------------------------------------------
# Export-frame assembly (still pure -- operates on in-memory DataFrames/sets)
# --------------------------------------------------------------------------


def _select_key_rows(
    df: pd.DataFrame, key_columns: list[str], keys: set, kf: pd.Series
) -> pd.DataFrame:
    """One representative row's key-column values per key in ``keys``.

    All rows sharing a composite key have identical key-column values by
    construction, so "first occurrence" is an arbitrary but safe pick when a
    key is duplicated.
    """
    if not keys:
        return pd.DataFrame(columns=list(key_columns))
    mask = kf.isin(keys)
    subset = df.loc[mask, key_columns].copy()
    subset["_key"] = kf[mask]
    subset = subset.drop_duplicates(subset="_key", keep="first").drop(columns="_key")
    return subset.reset_index(drop=True)


def _build_export_frame(
    df_left: pd.DataFrame,
    df_right: pd.DataFrame,
    key_columns: list[str],
    classification: dict[str, set],
    kf_left: pd.Series,
    kf_right: pd.Series,
) -> pd.DataFrame:
    """One row per non-inner key: ``<key columns...>, status`` (Exports section).

    duplicate_both keys are represented from the left side (any representative
    row works, see ``_select_key_rows``).
    """
    sources: dict[str, tuple[pd.DataFrame, pd.Series]] = {
        _LEFT_ONLY: (df_left, kf_left),
        _RIGHT_ONLY: (df_right, kf_right),
        _DUPLICATE_LEFT: (df_left, kf_left),
        _DUPLICATE_RIGHT: (df_right, kf_right),
        _DUPLICATE_BOTH: (df_left, kf_left),
    }

    frames = []
    for status in _NON_INNER_STATUSES:
        keys = classification[status]
        if not keys:
            continue
        source_df, kf = sources[status]
        rows = _select_key_rows(source_df, key_columns, keys, kf)
        rows[_STATUS_COLUMN] = status
        frames.append(rows)

    if not frames:
        return pd.DataFrame(columns=[*key_columns, _STATUS_COLUMN])
    return pd.concat(frames, ignore_index=True)


def _build_summary(
    classification: dict[str, set], dup_left_keys: set, dup_right_keys: set
) -> dict[str, int]:
    """Dashboard/PDF bar-chart counts (D14): left_only, inner, right_only, duplicates.

    NOTE on "duplicates" (spec doesn't pin this down precisely): it counts
    *distinct duplicated keys* -- the union of keys repeated in left and keys
    repeated in right (D8: "rows whose key is duplicated in either file are
    counted") -- not row counts, and NOT restricted to keys that also landed
    in a duplicate_left/duplicate_right/duplicate_both bucket above. So a key
    duplicated in one file but entirely absent from the other (e.g.
    row_drift_dupes' id=1: 2 rows in left, 0 in right) is counted both under
    its presence status (``left_only``) *and* here under ``duplicates`` --
    this is intentionally not a strict partition, it mirrors
    ``tests/test_pdf.py::test_full_layer3_style_report``'s expected counts
    for that exact fixture.
    """
    return {
        _LEFT_ONLY: len(classification[_LEFT_ONLY]),
        _INNER: len(classification[_INNER]),
        _RIGHT_ONLY: len(classification[_RIGHT_ONLY]),
        "duplicates": len(dup_left_keys | dup_right_keys),
        # A true disjoint partition of every key (unlike "duplicates" above,
        # which is a distinct-key union) for the row-match "set map": each key
        # lands in exactly one bucket. Read left-to-right this is the diagram
        # order dupes-left | left-only | inner | right-only | dupes-right, with
        # dupes-both (duplicated on *both* sides) tucked beside the inner block.
        # A nested object so the dashboard's summary tiles skip it and only the
        # chart consumes it.
        "row_map": {
            "dupes_left": len(classification[_DUPLICATE_LEFT]),
            "left_only": len(classification[_LEFT_ONLY]),
            "inner": len(classification[_INNER]),
            "right_only": len(classification[_RIGHT_ONLY]),
            "dupes_right": len(classification[_DUPLICATE_RIGHT]),
            "dupes_both": len(classification[_DUPLICATE_BOTH]),
        },
    }


# --------------------------------------------------------------------------
# run
# --------------------------------------------------------------------------


def run(layer1_result: LayerResult, layer2_result: LayerResult, config: Any) -> LayerResult:
    """Classify df_left/df_right rows by ``config.KEY_COLUMNS`` (D2, composite-safe).

    ``layer2_result.extras["common_columns"]`` is accepted for interface
    parity with the other layers' ``run(layer_n_result, ..., config)``
    signatures, but row pairing here is purely a function of the key
    columns -- it is not otherwise used: layer 2's gate already guarantees
    the key columns are a subset of the common set (D2) by the time layer 3
    runs, so there is nothing left for layer 3 to validate against it.
    """
    df_left: pd.DataFrame = layer1_result.extras["df_left"]
    df_right: pd.DataFrame = layer1_result.extras["df_right"]
    _common_columns = layer2_result.extras["common_columns"]  # noqa: F841 (see docstring)
    key_columns = list(config.KEY_COLUMNS)

    left_keys = unique_keys(df_left, key_columns)
    right_keys = unique_keys(df_right, key_columns)
    dup_left_keys = find_duplicates(df_left, key_columns)
    dup_right_keys = find_duplicates(df_right, key_columns)

    classification = classify_keys(left_keys, right_keys, dup_left_keys, dup_right_keys)
    verdict = row_verdict(classification)

    kf_left = key_frame(df_left, key_columns)
    kf_right = key_frame(df_right, key_columns)
    data = _build_export_frame(df_left, df_right, key_columns, classification, kf_left, kf_right)
    summary = _build_summary(classification, dup_left_keys, dup_right_keys)

    extras = {
        "inner_keys": classification[_INNER],
        "summary": summary,
        "key_columns": key_columns,
    }
    return LayerResult(name="layer_3_compare_rows", verdict=verdict, data=data, extras=extras)


# --------------------------------------------------------------------------
# export / report (I/O -- the only impure functions in this module)
# --------------------------------------------------------------------------


def _resolve_files(ctx: ExecutionContext) -> dict[str, dict[str, Any]]:
    """Original file paths/encodings, from layer 1's recorded result (D12).

    Falls back to the configured input paths with ``encoding: None`` if
    layer 1 has not been recorded on ``ctx`` yet, mirroring
    ``ExecutionContext.manifest_dict``'s fallback so export/report never
    crash on an out-of-order call.
    """
    layer_1 = ctx.results.get("layer_1_read")
    if layer_1 is not None and "files" in layer_1.extras:
        return layer_1.extras["files"]
    return {
        "left": {"path": str(ctx.config.INPUT_LEFT), "encoding": None},
        "right": {"path": str(ctx.config.INPUT_RIGHT), "encoding": None},
    }


def export(result: LayerResult, ctx: ExecutionContext) -> None:
    """Write ``layer_3_compare_rows.csv``/``.txt`` from ``result.data`` (D12).

    Always called before the gate runs, including on a ``failed`` verdict
    (architecture.md's layer contract) -- never call ``.to_csv`` directly,
    always go through ``src/utils/artifacts.py``'s writers.
    """
    write_csv(result.data, ctx.csv_path(result.name))

    files = _resolve_files(ctx)
    header_lines = [
        "Layer 3 - Compare Rows",
        f"Left file:  {files['left']['path']}   (encoding: {files['left']['encoding']})",
        f"Right file: {files['right']['path']}   (encoding: {files['right']['encoding']})",
        f"Verdict:    {result.verdict}",
        f"Generated:  {ctx.created_at.isoformat(timespec='seconds')}",
    ]
    write_txt(result.data, ctx.txt_path(result.name), header_lines=header_lines)


#: (row_map key, chart label, region kind) for the set-map, in reading order.
_ROW_MAP_REGIONS: tuple[tuple[str, str, str], ...] = (
    ("dupes_left", "dupes left", "dupes"),
    ("left_only", "left only", "only"),
    ("inner", "inner", "inner"),
    ("dupes_both", "dupes both", "both"),
    ("right_only", "right only", "only"),
    ("dupes_right", "dupes right", "dupes"),
)


def report(result: LayerResult, ctx: ExecutionContext) -> None:
    """Write ``layer_3_compare_rows.pdf``: header + verdict banner + summary +
    the row-match "set map" (dupes-left/left-only/inner/right-only/dupes-right,
    D14)."""
    files = _resolve_files(ctx)

    builder = ReportBuilder(
        title="Layer 3 - Compare Rows",
        left_file=files["left"]["path"],
        right_file=files["right"]["path"],
        left_encoding=files["left"]["encoding"],
        right_encoding=files["right"]["encoding"],
        verdict=result.verdict,
        timestamp=ctx.created_at,
    )

    summary = result.extras.get("summary", {})
    categories = [_LEFT_ONLY, _INNER, _RIGHT_ONLY, "duplicates"]
    counts = [summary.get(c, 0) for c in categories]

    summary_df = pd.DataFrame({"category": categories, "count": counts})
    builder.add_table(summary_df, heading="Row match summary")

    row_map = summary.get("row_map", {})
    regions = [(label, row_map.get(key, 0), kind) for key, label, kind in _ROW_MAP_REGIONS]
    builder.add_chart(set_partition_chart(regions, title="Row match map"))

    builder.output(str(ctx.pdf_path(result.name)))
