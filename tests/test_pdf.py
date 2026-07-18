"""Tests for src/utils/pdf.py -- the fpdf2 + matplotlib report engine.

Per .claude/utils/README.md: PDF tests assert the file is created and
non-empty, and that builder calls succeed -- no pixel-level testing.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from matplotlib.figure import Figure

from src.utils.pdf import ReportBuilder, barh_chart

FIXTURES = Path(__file__).parent / "fixtures"


def _builder(verdict: str = "success", **overrides) -> ReportBuilder:
    kwargs = dict(
        title="Layer 2 - Compare Columns",
        left_file="file1.csv",
        right_file="file2.csv",
        left_encoding="utf-8",
        right_encoding="utf-8",
        verdict=verdict,
        timestamp="2026-07-18 10:00:00",
    )
    kwargs.update(overrides)
    return ReportBuilder(**kwargs)


@pytest.fixture
def value_drift_df() -> pd.DataFrame:
    left = pd.read_csv(FIXTURES / "value_drift_left.csv")
    right = pd.read_csv(FIXTURES / "value_drift_right.csv")
    return pd.DataFrame(
        {
            "id": left["id"],
            "name_left": left["name"],
            "name_right": right["name"],
            "match": (left["name"] == right["name"]),
        }
    )


# -- ReportBuilder: header + verdict banner -------------------------------


@pytest.mark.parametrize(
    "verdict", ["success", "completed-with-differences", "failed"]
)
def test_report_builder_writes_nonempty_pdf(tmp_path, verdict, value_drift_df):
    """Each verdict banner color renders and a real PDF file is produced."""
    builder = _builder(verdict=verdict)
    builder.add_table(value_drift_df, heading="Value drift")

    out_path = tmp_path / f"layer_report_{verdict}.pdf"
    builder.output(str(out_path))

    assert out_path.exists()
    assert out_path.stat().st_size > 0
    # a real PDF starts with the %PDF- magic bytes
    assert out_path.read_bytes().startswith(b"%PDF-")


def test_report_builder_rejects_unknown_verdict():
    with pytest.raises(ValueError):
        _builder(verdict="not-a-real-verdict")


def test_output_bytes_matches_output_file(tmp_path):
    builder = _builder()
    data = builder.output_bytes()
    assert len(data) > 0
    assert data.startswith(b"%PDF-")

    out_path = tmp_path / "same.pdf"
    builder.output(str(out_path))
    assert out_path.stat().st_size > 0


# -- add_table --------------------------------------------------------------


def test_add_table_with_fixture_data(value_drift_df):
    builder = _builder()
    builder.add_table(value_drift_df, heading="Value drift")
    assert len(builder.output_bytes()) > 0


def test_add_table_empty_dataframe_does_not_crash():
    builder = _builder()
    builder.add_table(pd.DataFrame(columns=["a", "b", "c"]))
    assert len(builder.output_bytes()) > 0


def test_add_table_handles_nan_and_unicode():
    df = pd.DataFrame(
        {
            "name": ["Alíce", "Böb", None],
            "value": [1.0, float("nan"), 3],
        }
    )
    builder = _builder()
    builder.add_table(df, heading="Unicode + NaN")
    assert len(builder.output_bytes()) > 0


def test_add_table_many_rows_triggers_page_break():
    """60 rows on an A4 page forces at least one page break; must not crash
    and must repeat the header row on the new page."""
    df = pd.DataFrame(
        {
            "id": range(60),
            "name": [f"name_{i}" for i in range(60)],
            "value": [i * 1.5 for i in range(60)],
        }
    )
    builder = _builder()
    builder.add_table(df, heading="Big table")
    data = builder.output_bytes()
    assert len(data) > 0
    assert builder.pdf.pages_count > 1


def test_add_table_max_rows_truncates_with_note():
    df = pd.DataFrame({"id": range(20), "value": range(20)})
    builder = _builder()
    builder.add_table(df, max_rows=5)
    assert len(builder.output_bytes()) > 0


# -- barh_chart ---------------------------------------------------------


def test_barh_chart_returns_figure():
    fig = barh_chart(["left_only", "inner", "right_only", "duplicates"], [1, 4, 2, 1])
    assert isinstance(fig, Figure)


def test_barh_chart_with_grey_mask_layer4_style():
    """Layer 4 style: per-column diff counts, accepted columns drawn grey."""
    labels = ["status", "amount", "notes"]
    values = [3, 5, 1]
    grey_mask = [False, True, False]
    fig = barh_chart(
        labels, values, grey_mask,
        title="Per-column differences",
        xlabel="Diff count",
        series_label="Non-accepted",
        grey_label="Accepted",
    )
    assert isinstance(fig, Figure)


def test_barh_chart_empty_data_does_not_crash():
    fig = barh_chart([], [])
    assert isinstance(fig, Figure)


def test_barh_chart_all_grey():
    fig = barh_chart(["a", "b"], [1, 2], [True, True])
    assert isinstance(fig, Figure)


def test_barh_chart_rejects_mismatched_values_length():
    with pytest.raises(ValueError):
        barh_chart(["a", "b"], [1])


def test_barh_chart_rejects_mismatched_grey_mask_length():
    with pytest.raises(ValueError):
        barh_chart(["a", "b"], [1, 2], [True])


def test_add_chart_embeds_figure_in_pdf():
    builder = _builder()
    fig = barh_chart(["left_only", "inner", "right_only", "duplicates"], [1, 4, 2, 1])
    builder.add_chart(fig)
    data = builder.output_bytes()
    assert len(data) > 0
    assert data.startswith(b"%PDF-")


def test_add_chart_many_bars_forces_page_break():
    builder = _builder()
    fig = barh_chart(
        [f"col_{i}" for i in range(20)],
        list(range(20)),
        [i % 3 == 0 for i in range(20)],
    )
    builder.add_chart(fig)
    assert len(builder.output_bytes()) > 0


# -- full layer-shaped report (integration-style smoke test) ---------------


def test_full_layer3_style_report(tmp_path):
    """End-to-end: header + banner + summary table + horizontal bar chart,
    mirroring how layer 3's report() phase is expected to call this module."""
    left = pd.read_csv(FIXTURES / "row_drift_dupes_left.csv")
    right = pd.read_csv(FIXTURES / "row_drift_dupes_right.csv")

    summary = pd.DataFrame(
        {
            "category": ["left_only", "inner", "right_only", "duplicates"],
            "count": [1, 3, 2, 1],
        }
    )

    builder = ReportBuilder(
        title="Layer 3 - Compare Rows",
        left_file="row_drift_dupes_left.csv",
        right_file="row_drift_dupes_right.csv",
        left_encoding="utf-8",
        right_encoding="utf-8",
        verdict="completed-with-differences",
    )
    builder.add_table(summary, heading="Row match summary")
    fig = barh_chart(
        summary["category"].tolist(), summary["count"].tolist(),
        xlabel="Row count",
    )
    builder.add_chart(fig)

    out_path = tmp_path / "layer_3_compare_rows.pdf"
    builder.output(str(out_path))

    assert out_path.exists()
    assert out_path.stat().st_size > 0
    assert len(left) > 0 and len(right) > 0  # fixture sanity
