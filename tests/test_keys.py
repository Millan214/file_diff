"""Tests for src/utils/keys.py (composite-key + duplicate helpers, D2/D8)."""

from __future__ import annotations

import pandas as pd
import pytest

from src.utils.keys import (
    MissingKeyColumnsError,
    duplicate_mask,
    key_frame,
    unique_keys,
)


def test_key_frame_single_column(fixtures_dir):
    df = pd.read_csv(fixtures_dir / "identical_left.csv")
    keys = key_frame(df, ["id"])
    assert list(keys) == [("1",), ("2",), ("3",), ("4",), ("5",)]
    assert keys.name == "_key"


def test_key_frame_missing_column_raises(fixtures_dir):
    df = pd.read_csv(fixtures_dir / "identical_left.csv")
    with pytest.raises(MissingKeyColumnsError):
        key_frame(df, ["not_a_column"])


def test_key_frame_composite_key_order_and_columns():
    df = pd.DataFrame(
        {
            "id": [1, 1, 2],
            "region": ["east", "west", "east"],
            "value": [10, 20, 30],
        }
    )
    keys = key_frame(df, ["id", "region"])
    assert list(keys) == [("1", "east"), ("1", "west"), ("2", "east")]


def test_key_frame_dtype_drift_normalizes_int_and_float_equal():
    """D7: an id column int64 on one side, float64 on the other, must still
    produce matching composite keys for logically-equal values."""
    left = pd.DataFrame({"id": pd.array([1, 2, 3], dtype="int64"), "v": [1, 2, 3]})
    right = pd.DataFrame({"id": pd.array([1.0, 2.0, 3.0], dtype="float64"), "v": [1, 2, 3]})

    left_keys = list(key_frame(left, ["id"]))
    right_keys = list(key_frame(right, ["id"]))
    assert left_keys == right_keys == [("1",), ("2",), ("3",)]


def test_key_frame_non_integer_float_key_is_not_mangled():
    df = pd.DataFrame({"id": [1.5, 2.25]})
    keys = list(key_frame(df, ["id"]))
    assert keys == [("1.5",), ("2.25",)]


def test_key_frame_nan_key_maps_to_consistent_sentinel():
    df = pd.DataFrame({"id": [1, float("nan"), float("nan")]})
    keys = list(key_frame(df, ["id"]))
    # Both NaN rows get the same (non-"1") sentinel key.
    assert keys[0] == ("1",)
    assert keys[1] == keys[2]
    assert keys[1] != keys[0]


def test_duplicate_mask_flags_all_occurrences_of_a_repeated_key(fixtures_dir):
    left = pd.read_csv(fixtures_dir / "row_drift_dupes_left.csv")
    mask = duplicate_mask(left, ["id"])
    # Fixture: id=1 appears twice (rows 0, 1); ids 2-4 are unique in this file.
    assert list(mask) == [True, True, False, False, False]


def test_unique_keys_classification_matches_fixture_expectations(fixtures_dir):
    left = pd.read_csv(fixtures_dir / "row_drift_dupes_left.csv")
    right = pd.read_csv(fixtures_dir / "row_drift_dupes_right.csv")

    left_keys = unique_keys(left, ["id"])
    right_keys = unique_keys(right, ["id"])

    left_only = left_keys - right_keys
    inner = left_keys & right_keys
    right_only = right_keys - left_keys

    assert left_only == {("1",)}
    assert inner == {("2",), ("3",), ("4",)}
    assert right_only == {("5",), ("6",)}
