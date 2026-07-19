"""Layer 3 outputs -- CSV/TXT exports and the PDF report.

The only impure functions in this layer; both are thin wrappers around
``src/utils/artifacts.py`` and ``src/utils/pdf.py``. Always called before the
pipeline decides to continue, including on a ``failed`` verdict
(architecture.md's layer contract).
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.utils.artifacts import write_csv, write_txt
from src.utils.execution import ExecutionContext, LayerResult
from src.utils.pdf import ReportBuilder, set_partition_chart

from .logic import _INNER, _LEFT_ONLY, _RIGHT_ONLY


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

    Always called before the pipeline decides to continue, including on a
    ``failed`` verdict (architecture.md's layer contract) -- never call
    ``.to_csv`` directly, always go through ``src/utils/artifacts.py``.
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
