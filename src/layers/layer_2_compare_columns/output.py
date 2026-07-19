"""Layer 2 outputs -- CSV/TXT exports and the PDF report.

The only I/O in this layer, delegating all file writing to
``src/utils/artifacts.py`` and ``src/utils/pdf.py`` (architecture.md's layer
contract -- artifacts are always written before the pipeline decides to
continue, even on a ``failed`` verdict).
"""

from __future__ import annotations

from typing import Any

from src.utils.artifacts import write_csv, write_txt
from src.utils.execution import ExecutionContext, LayerResult
from src.utils.pdf import ReportBuilder


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
