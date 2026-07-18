"""Tests for src/utils/artifacts.py (CSV/TXT writers, D12)."""

from __future__ import annotations

import pandas as pd

from src.utils.artifacts import write_csv, write_txt


def _sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id": [1, 2, 3, 4, 5],
            "name": ["Alice", "Bob", "Charlie", "Diana", "Eve"],
            "value": [100, 200, 300, 400, 500],
        }
    )


def test_write_csv_round_trips_without_index(tmp_path):
    df = _sample_df()
    path = write_csv(df, tmp_path / "out.csv")

    assert path.exists()
    content = path.read_text(encoding="utf-8")
    # No pandas index column written.
    assert not content.startswith(",")
    round_tripped = pd.read_csv(path)
    pd.testing.assert_frame_equal(round_tripped, df)


def test_write_csv_creates_parent_directories(tmp_path):
    nested = tmp_path / "execution=x" / "layer_1_read" / "layer_1_read.csv"
    write_csv(_sample_df(), nested)
    assert nested.exists()


def test_write_csv_preserves_utf8_accented_characters(tmp_path, fixtures_dir):
    df = pd.read_csv(fixtures_dir / "encoding_conflict_left.csv")
    path = write_csv(df, tmp_path / "accented.csv")

    round_tripped = pd.read_csv(path, encoding="utf-8")
    pd.testing.assert_frame_equal(round_tripped, df)
    assert "Alíce" in path.read_text(encoding="utf-8")


def test_write_txt_includes_header_lines_then_fixed_width_table(tmp_path):
    df = _sample_df()
    header = [
        "Layer 1 - Read",
        "Left file: left.csv (encoding: utf-8)",
        "Verdict: success",
    ]
    path = write_txt(df, tmp_path / "out.txt", header_lines=header)
    content = path.read_text(encoding="utf-8")

    lines = content.splitlines()
    assert lines[: len(header)] == header
    assert lines[len(header)] == ""  # blank separator
    table_section = "\n".join(lines[len(header) + 1 :])
    assert table_section.rstrip("\n") == df.to_string(index=False)


def test_write_txt_without_header_lines_is_just_the_table(tmp_path):
    df = _sample_df()
    path = write_txt(df, tmp_path / "out.txt")
    content = path.read_text(encoding="utf-8")

    assert content.rstrip("\n") == df.to_string(index=False)


def test_write_txt_matches_csv_data_exactly(tmp_path):
    """Same DataFrame -> the TXT table renders every value the CSV has (D12)."""
    df = _sample_df()
    csv_path = write_csv(df, tmp_path / "layer.csv")
    txt_path = write_txt(df, tmp_path / "layer.txt", header_lines=["Verdict: success"])

    csv_values = pd.read_csv(csv_path)
    txt_content = txt_path.read_text(encoding="utf-8")
    for value in csv_values["name"]:
        assert str(value) in txt_content
