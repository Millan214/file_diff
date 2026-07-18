"""PDF report engine (fpdf2 + matplotlib).

Builds the per-layer PDF reports described in ``.claude/docs/architecture.md``:
a standard header (title, file names, encodings, timestamp), a three-color
verdict banner (green success / amber completed-with-differences / red
failed), DataFrame tables, and horizontal bar charts.

Charts are matplotlib figures rendered to PNG **in-memory** (``io.BytesIO``)
and embedded straight into the PDF -- no temporary files ever touch disk.

Colors follow the ``dataviz`` skill's validated default palette (light mode
only: a PDF report is a print/light medium, so the dark-surface half of the
palette is not applicable here).
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Sequence

import matplotlib

matplotlib.use("Agg")  # headless backend: no display, no temp files

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import pandas as pd
from fpdf import FPDF
from fpdf.enums import Align, XPos, YPos
from matplotlib.figure import Figure
from matplotlib.patches import Patch

RGB = tuple[int, int, int]

# --------------------------------------------------------------------------
# Design tokens -- dataviz skill palette, light mode (see references/
# palette.md and references/marks-and-anatomy.md in the dataviz skill).
# --------------------------------------------------------------------------

_SURFACE: RGB = (252, 252, 251)  # #fcfcfb  chart/page surface
_PRIMARY_INK: RGB = (11, 11, 11)  # #0b0b0b  primary text
_SECONDARY_INK: RGB = (82, 81, 78)  # #52514e  secondary text
_MUTED_INK: RGB = (137, 135, 129)  # #898781  muted axis/labels
_GRIDLINE: RGB = (225, 224, 217)  # #e1e0d9  hairline gridline
_BASELINE: RGB = (195, 194, 183)  # #c3c2b7  baseline/axis line
_WHITE: RGB = (255, 255, 255)

_SERIES_1: RGB = (42, 120, 214)  # #2a78d6  categorical slot 1 (blue)
_GREY_BAR: RGB = _MUTED_INK  # grey fill for de-emphasized/accepted bars (D3)

_STATUS_GOOD: RGB = (12, 163, 12)  # #0ca30c
_STATUS_WARNING: RGB = (250, 178, 25)  # #fab219
_STATUS_CRITICAL: RGB = (208, 59, 59)  # #d03b3b

_FONT = "helvetica"

# Verdict -> banner fill / text color / label (D3, architecture.md).
_VERDICT_STYLES: dict[str, dict] = {
    "success": {"fill": _STATUS_GOOD, "text": _WHITE, "label": "SUCCESS"},
    "completed-with-differences": {
        "fill": _STATUS_WARNING,
        "text": _PRIMARY_INK,
        "label": "COMPLETED WITH DIFFERENCES",
    },
    "failed": {"fill": _STATUS_CRITICAL, "text": _WHITE, "label": "FAILED"},
}


def _hex(rgb: RGB) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _safe_text(value: object) -> str:
    """Coerce to str and drop characters the core PDF fonts cannot encode.

    fpdf2's built-in (non-embedded) fonts only support the latin-1 / cp1252
    range. Upstream data (CSV cells) may contain arbitrary unicode, so this
    is a defensive re-encode rather than a real internationalization layer.
    """
    text = "" if value is None else str(value)
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _cell_text(value: object) -> str:
    """Render a single DataFrame cell for a PDF table."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, float):
        try:
            if value.is_integer():
                return _safe_text(int(value))
        except (OverflowError, ValueError):
            pass
    return _safe_text(value)


def _truncate(text: str, width_mm: float, pdf: FPDF, padding: float = 2.0) -> str:
    """Shorten `text` with an ellipsis so it fits in a column of `width_mm`."""
    max_w = max(width_mm - padding, 1.0)
    if pdf.get_string_width(text) <= max_w:
        return text
    suffix = "..."
    trimmed = text
    while trimmed and pdf.get_string_width(trimmed + suffix) > max_w:
        trimmed = trimmed[:-1]
    return f"{trimmed}{suffix}" if trimmed else suffix


class ReportBuilder:
    """Builds one layer's PDF report: header, verdict banner, tables, charts.

    Example::

        builder = ReportBuilder(
            title="Layer 2 - Compare Columns",
            left_file="file1.csv",
            right_file="file2.csv",
            left_encoding="utf-8",
            right_encoding="utf-8",
            verdict="completed-with-differences",
        )
        builder.add_table(dtype_df, heading="Column dtypes")
        builder.add_chart(barh_chart(labels, values))
        builder.output(path)
    """

    _MARGIN = 15.0

    def __init__(
        self,
        *,
        title: str,
        left_file: str,
        right_file: str,
        left_encoding: str,
        right_encoding: str,
        verdict: str,
        timestamp: datetime | str | None = None,
    ) -> None:
        if verdict not in _VERDICT_STYLES:
            raise ValueError(
                f"Unknown verdict {verdict!r}; expected one of {sorted(_VERDICT_STYLES)}"
            )

        self.pdf = FPDF(orientation="P", unit="mm", format="A4")
        self.pdf.set_margins(self._MARGIN, self._MARGIN, self._MARGIN)
        self.pdf.set_auto_page_break(auto=True, margin=self._MARGIN)
        self.pdf.set_title(_safe_text(title))
        self.pdf.add_page()

        self._write_header(title, left_file, right_file, left_encoding, right_encoding, timestamp)
        self._write_verdict_banner(verdict)

    # -- header ------------------------------------------------------------
    def _write_header(
        self,
        title: str,
        left_file: str,
        right_file: str,
        left_encoding: str,
        right_encoding: str,
        timestamp: datetime | str | None,
    ) -> None:
        pdf = self.pdf
        pdf.set_text_color(*_PRIMARY_INK)
        pdf.set_font(_FONT, style="B", size=18)
        pdf.cell(0, 10, _safe_text(title), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        if timestamp is None:
            ts_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(timestamp, datetime):
            ts_text = timestamp.strftime("%Y-%m-%d %H:%M:%S")
        else:
            ts_text = str(timestamp)

        pdf.set_font(_FONT, style="", size=10)
        pdf.set_text_color(*_SECONDARY_INK)
        info_lines = [
            f"Left file:  {left_file}   (encoding: {left_encoding})",
            f"Right file: {right_file}   (encoding: {right_encoding})",
            f"Generated:  {ts_text}",
        ]
        for line in info_lines:
            pdf.cell(0, 6, _safe_text(line), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        pdf.ln(2)
        pdf.set_draw_color(*_GRIDLINE)
        pdf.set_line_width(0.3)
        y = pdf.get_y()
        pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
        pdf.ln(4)

    # -- verdict banner ------------------------------------------------------
    def _write_verdict_banner(self, verdict: str) -> None:
        pdf = self.pdf
        style = _VERDICT_STYLES[verdict]
        pdf.set_fill_color(*style["fill"])
        pdf.set_text_color(*style["text"])
        pdf.set_font(_FONT, style="B", size=13)
        pdf.cell(
            0, 10, style["label"], border=0, align="C", fill=True,
            new_x=XPos.LMARGIN, new_y=YPos.NEXT,
        )
        pdf.set_text_color(*_PRIMARY_INK)
        pdf.ln(4)

    # -- text helpers ---------------------------------------------------
    def add_heading(self, text: str) -> None:
        """Section heading, e.g. before a table or chart."""
        pdf = self.pdf
        pdf.set_font(_FONT, style="B", size=12)
        pdf.set_text_color(*_PRIMARY_INK)
        pdf.cell(0, 8, _safe_text(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(1)

    def add_paragraph(self, text: str) -> None:
        """Free-text note (e.g. accepted-difference reasons, missing-file notes)."""
        pdf = self.pdf
        pdf.set_font(_FONT, style="", size=10)
        pdf.set_text_color(*_SECONDARY_INK)
        pdf.multi_cell(0, 5.5, _safe_text(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_text_color(*_PRIMARY_INK)
        pdf.ln(1)

    # -- table ------------------------------------------------------------
    def add_table(
        self,
        df: pd.DataFrame,
        *,
        heading: str | None = None,
        max_rows: int | None = None,
    ) -> None:
        """Render a DataFrame as a simple ruled/zebra PDF table."""
        pdf = self.pdf

        if heading:
            self.add_heading(heading)

        if df is None or df.empty:
            self.add_paragraph("(no rows)")
            return

        display_df = df if max_rows is None else df.head(max_rows)
        columns = list(display_df.columns)

        col_chars = [
            max([len(str(col))] + [len(_cell_text(v)) for v in display_df[col]])
            for col in columns
        ]
        total_chars = sum(col_chars) or 1
        avail_width = pdf.epw
        min_width = 18.0
        widths = [max(min_width, avail_width * chars / total_chars) for chars in col_chars]
        scale = avail_width / sum(widths)
        widths = [w * scale for w in widths]

        row_h = 7.0
        numeric_cols = {c for c in columns if pd.api.types.is_numeric_dtype(display_df[c])}

        def draw_header_row() -> None:
            pdf.set_font(_FONT, style="B", size=9)
            pdf.set_fill_color(*_GRIDLINE)
            pdf.set_text_color(*_PRIMARY_INK)
            for w, col in zip(widths, columns):
                pdf.cell(w, row_h, _truncate(_safe_text(col), w, pdf), border=0, align="L", fill=True)
            pdf.ln(row_h)

        draw_header_row()

        for i, (_, row) in enumerate(display_df.iterrows()):
            if pdf.will_page_break(row_h):
                pdf.add_page()
                draw_header_row()

            fill = i % 2 == 1
            pdf.set_font(_FONT, style="", size=9)
            pdf.set_fill_color(*(_SURFACE if fill else _WHITE))
            pdf.set_text_color(*_PRIMARY_INK)
            for w, col in zip(widths, columns):
                text = _cell_text(row[col])
                align = "R" if col in numeric_cols else "L"
                pdf.cell(w, row_h, _truncate(text, w, pdf), border=0, align=align, fill=fill)
            pdf.ln(row_h)

        if max_rows is not None and len(df) > max_rows:
            pdf.set_font(_FONT, style="I", size=8)
            pdf.set_text_color(*_MUTED_INK)
            pdf.cell(
                0, 6, f"... {len(df) - max_rows} more rows omitted",
                new_x=XPos.LMARGIN, new_y=YPos.NEXT,
            )

        pdf.set_text_color(*_PRIMARY_INK)
        pdf.ln(3)

    # -- chart ------------------------------------------------------------
    def add_chart(self, fig: Figure, *, width_mm: float | None = None) -> None:
        """Embed a matplotlib figure as a PNG rendered in-memory (no temp files)."""
        pdf = self.pdf

        fig_w_in, fig_h_in = fig.get_size_inches()
        aspect = (fig_h_in / fig_w_in) if fig_w_in else 0.5

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=200, bbox_inches="tight", facecolor=fig.get_facecolor())
        plt.close(fig)
        buf.seek(0)

        w = width_mm if width_mm is not None else pdf.epw
        est_h = w * aspect
        if pdf.will_page_break(est_h):
            pdf.add_page()

        pdf.image(buf, x=Align.C, w=w)
        pdf.ln(4)

    # -- output -------------------------------------------------------------
    def output(self, path: str) -> None:
        """Write the finished PDF to `path`."""
        self.pdf.output(str(path))

    def output_bytes(self) -> bytes:
        """Return the finished PDF as bytes, without touching disk (for tests)."""
        return bytes(self.pdf.output())


# --------------------------------------------------------------------------
# Charts
# --------------------------------------------------------------------------


def barh_chart(
    labels: Sequence[str],
    values: Sequence[float],
    grey_mask: Sequence[bool] | None = None,
    *,
    title: str | None = None,
    xlabel: str | None = None,
    series_label: str | None = None,
    grey_label: str | None = None,
) -> Figure:
    """Horizontal bar chart: category labels on the y-axis, magnitude on the
    x-axis (D14 -- both layer 3's left/inner/right/duplicate counts and
    layer 4's per-column diff counts use this orientation).

    `grey_mask[i]` True renders bar `i` in the muted grey token instead of
    the default series color -- used for layer 4's accepted-difference
    columns (D3), and reusable for layer 3's summary bars.

    When `grey_mask` mixes True and False, pass `series_label`/`grey_label`
    to render a two-swatch legend (identity must not rely on color alone).

    Returns the matplotlib Figure; the caller embeds it via
    `ReportBuilder.add_chart` (rendered to PNG in-memory, no temp files).
    """
    labels = list(labels)
    values = list(values)
    n = len(labels)
    if len(values) != n:
        raise ValueError(f"labels and values must be the same length, got {n} and {len(values)}")

    if grey_mask is None:
        grey_mask = [False] * n
    else:
        grey_mask = list(grey_mask)
        if len(grey_mask) != n:
            raise ValueError(f"grey_mask must match labels length, got {len(grey_mask)} and {n}")

    fig_height = max(2.2, 0.45 * max(n, 1) + 1.1)
    fig, ax = plt.subplots(figsize=(7.2, fig_height), dpi=150)
    fig.patch.set_facecolor(_hex(_SURFACE))
    ax.set_facecolor(_hex(_SURFACE))

    if n == 0:
        ax.text(
            0.5, 0.5, "No data", ha="center", va="center",
            color=_hex(_MUTED_INK), fontsize=11, transform=ax.transAxes,
        )
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)
        fig.tight_layout()
        return fig

    # First label reads at the top, like a list.
    plot_labels = list(reversed(labels))
    plot_values = list(reversed(values))
    plot_grey = list(reversed(grey_mask))
    y_pos = range(n)

    colors = [_hex(_GREY_BAR) if grey else _hex(_SERIES_1) for grey in plot_grey]
    ax.barh(list(y_pos), plot_values, height=0.6, color=colors, zorder=3)

    ax.set_yticks(list(y_pos))
    ax.set_yticklabels([_safe_text(label) for label in plot_labels], color=_hex(_SECONDARY_INK), fontsize=10)
    ax.tick_params(axis="y", length=0)
    ax.tick_params(axis="x", colors=_hex(_MUTED_INK), labelsize=9, length=0)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _pos: f"{int(round(v)):,}"))

    max_val = max(plot_values) if plot_values else 0
    headroom = max_val * 0.15 if max_val > 0 else 1
    ax.set_xlim(0, (max_val + headroom) if max_val > 0 else 1)

    ax.grid(axis="x", color=_hex(_GRIDLINE), linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)

    for spine_name, spine in ax.spines.items():
        if spine_name == "bottom":
            spine.set_color(_hex(_BASELINE))
            spine.set_linewidth(0.8)
        else:
            spine.set_visible(False)

    # Direct value label at the tip of each bar (marks-and-anatomy: "Bars -> value at the tip").
    tip_offset = max(max_val, 1) * 0.02
    for y, v in zip(y_pos, plot_values):
        label = f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}"
        ax.text(v + tip_offset, y, label, va="center", ha="left", color=_hex(_PRIMARY_INK), fontsize=9)

    if xlabel:
        ax.set_xlabel(_safe_text(xlabel), color=_hex(_SECONDARY_INK), fontsize=10)
    if title:
        ax.set_title(_safe_text(title), color=_hex(_PRIMARY_INK), fontsize=12, fontweight="bold", loc="left")

    if series_label or grey_label:
        handles = []
        if series_label:
            handles.append(Patch(facecolor=_hex(_SERIES_1), label=_safe_text(series_label)))
        if grey_label:
            handles.append(Patch(facecolor=_hex(_GREY_BAR), label=_safe_text(grey_label)))
        ax.legend(
            handles=handles, loc="lower right", frameon=False, fontsize=9,
            labelcolor=_hex(_SECONDARY_INK),
        )

    fig.tight_layout()
    return fig
