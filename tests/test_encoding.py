"""Tests for src/utils/encoding.py (detection + D4 normalization)."""

from __future__ import annotations

import pytest

from src.utils.encoding import EncodingDetectionError, detect_encoding, normalize


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("ascii", "utf-8"),
        ("ASCII", "utf-8"),
        ("us-ascii", "utf-8"),
        ("utf-8-sig", "utf-8"),
        ("UTF_8_SIG", "utf-8"),
        ("utf-8", "utf-8"),
        ("utf_8", "utf-8"),
        ("cp1252", "cp1252"),
        ("ISO-8859-1", "iso-8859-1"),
    ],
)
def test_normalize(raw, expected):
    assert normalize(raw) == expected


def test_detect_encoding_plain_ascii_fixture_normalizes_to_utf8(fixtures_dir):
    result = detect_encoding(fixtures_dir / "identical_left.csv")
    assert result.normalized == "utf-8"


def test_detect_encoding_utf8_accented_fixture(fixtures_dir):
    result = detect_encoding(fixtures_dir / "encoding_conflict_left.csv")
    assert result.encoding == "utf-8"
    assert result.normalized == "utf-8"


def test_detect_encoding_ascii_fixture_of_conflict_pair(fixtures_dir):
    """The 'conflict' pair's right side is plain ASCII content.

    Per D4, ASCII is a strict subset of UTF-8, so detecting it here reports
    the raw encoding as ascii but normalizes to utf-8 -- matching the left
    side's utf-8 after normalization. Whether this pair is actually a
    conflict is layer 1's gate decision (a genuine mismatch needs the
    *normalized* encodings to differ); this test only pins encoding.py's
    own D4 contract.
    """
    result = detect_encoding(fixtures_dir / "encoding_conflict_right.csv")
    assert result.encoding == "ascii"
    assert result.normalized == "utf-8"


def test_detect_encoding_missing_file_raises(tmp_path):
    with pytest.raises(EncodingDetectionError):
        detect_encoding(tmp_path / "does_not_exist.csv")


def test_detected_encoding_bom_field_present(fixtures_dir):
    result = detect_encoding(fixtures_dir / "identical_left.csv")
    assert result.bom is False
