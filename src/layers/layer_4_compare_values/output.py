"""Layer 4 outputs -- CSV/TXT exports and the PDF report.

The only file-writing functions in this layer; always called before the
pipeline decides to continue, including on a ``failed`` verdict
(architecture.md's contract). All writing goes through
``src/utils/artifacts.py`` and ``src/utils/pdf.py``.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.utils.artifacts import write_csv, write_txt
from src.utils.execution import ExecutionContext, LayerResult
from src.utils.pdf import ReportBuilder, barh_chart


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

    Always called before the pipeline decides to continue, including on a
    ``failed`` verdict (architecture.md's contract); never calls ``.to_csv``
    directly.
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
