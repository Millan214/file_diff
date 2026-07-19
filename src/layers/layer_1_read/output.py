"""Layer 1 outputs -- CSV/TXT exports and the PDF report.

The only I/O in this layer besides ``logic.load_csv``/``detect_file_encoding``.
Always called before the pipeline decides to continue, including on a
``failed`` verdict (architecture.md's layer contract); all writing goes
through ``src/utils/artifacts.py`` and ``src/utils/pdf.py`` -- never
``.to_csv`` directly.
"""

from __future__ import annotations

from src.utils.artifacts import write_csv, write_txt
from src.utils.execution import ExecutionContext, LayerResult
from src.utils.pdf import ReportBuilder


def _header_lines(result: LayerResult, ctx: ExecutionContext) -> list[str]:
    left_enc = result.extras.get("left_encoding") or "unknown"
    right_enc = result.extras.get("right_encoding") or "unknown"
    files = result.extras.get("files", {})
    left_path = files.get("left", {}).get("path", str(ctx.config.INPUT_LEFT))
    right_path = files.get("right", {}).get("path", str(ctx.config.INPUT_RIGHT))
    return [
        f"Left file:  {left_path}   (encoding: {left_enc})",
        f"Right file: {right_path}   (encoding: {right_enc})",
        f"Verdict:    {result.verdict}",
        f"Generated:  {ctx.created_at.strftime('%Y-%m-%d %H:%M:%S')}",
    ]


def export(result: LayerResult, ctx: ExecutionContext) -> None:
    """Write the layer 1 CSV + TXT exports (D12). Never calls ``.to_csv`` directly."""
    write_csv(result.data, ctx.csv_path(result.name))
    write_txt(result.data, ctx.txt_path(result.name), header_lines=_header_lines(result, ctx))


def report(result: LayerResult, ctx: ExecutionContext) -> None:
    """Write the layer 1 PDF report: standard header + table + verdict banner."""
    files = result.extras.get("files", {})
    left_path = files.get("left", {}).get("path", str(ctx.config.INPUT_LEFT))
    right_path = files.get("right", {}).get("path", str(ctx.config.INPUT_RIGHT))

    builder = ReportBuilder(
        title="Layer 1 -- Read",
        left_file=left_path,
        right_file=right_path,
        left_encoding=result.extras.get("left_encoding") or "unknown",
        right_encoding=result.extras.get("right_encoding") or "unknown",
        verdict=result.verdict,
        timestamp=ctx.created_at,
    )
    builder.add_table(result.data, heading="Files")

    if result.verdict == "failed":
        reasons = result.extras.get("failure_reasons") or []
        reason_text = " | ".join(reasons) if reasons else "See status column above."
        builder.add_paragraph(f"Failing reason(s): {reason_text}")

    builder.output(str(ctx.pdf_path(result.name)))
