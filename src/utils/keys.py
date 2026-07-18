"""Composite-key and duplicate-key helpers shared by layers 3 and 4 (D2, D8).

Centralizing the composite-key representation here means layer 3's
left/inner/right classification and layer 4's row pairing can never drift
apart — both build keys the same way.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

#: Sentinel for a missing/NaN key value, distinguishable from any real
#: string representation of a value.
_NULL_KEY_MARKER = "\x00NULL\x00"


class MissingKeyColumnsError(KeyError):
    """Raised when one or more key columns are absent from a DataFrame."""


def _validate_key_columns(df: pd.DataFrame, key_columns: Sequence[str]) -> None:
    missing = [c for c in key_columns if c not in df.columns]
    if missing:
        raise MissingKeyColumnsError(
            f"Key column(s) not found in dataframe: {missing}"
        )


def _normalize_key_value(value: object) -> str:
    """Canonicalize one key value to a string.

    Dtype drift (D7) must not fracture otherwise-equal keys: an ``id``
    column read as ``int64`` on one side and ``float64`` on the other (e.g.
    because of an unrelated blank cell elsewhere) should still match 1 to
    1.0. NaN/None is mapped to a sentinel so missing-key rows are treated as
    equal to each other but distinct from any real value.
    """
    if value is None:
        return _NULL_KEY_MARKER
    if isinstance(value, float) and pd.isna(value):
        return _NULL_KEY_MARKER
    if isinstance(value, (float, np.floating)):
        as_float = float(value)
        if as_float.is_integer():
            return str(int(as_float))
        return repr(as_float)
    return str(value)


def key_frame(df: pd.DataFrame, key_columns: Sequence[str]) -> pd.Series:
    """Build a composite-key ``Series`` (one tuple per row), aligned to ``df``'s index.

    Each element is a tuple of the normalized string form of each key
    column's value, in ``key_columns`` order — hashable and directly usable
    with ``.duplicated()``, ``isin()``, ``set()``, etc.
    """
    _validate_key_columns(df, key_columns)
    key_columns = list(key_columns)
    keys = df[key_columns].apply(
        lambda row: tuple(_normalize_key_value(v) for v in row), axis=1
    )
    keys.name = "_key"
    return keys


def duplicate_mask(df: pd.DataFrame, key_columns: Sequence[str]) -> pd.Series:
    """Boolean mask aligned to ``df``'s index.

    ``True`` for every row whose composite key appears more than once in
    ``df`` (i.e. keys "appearing >1 time in a file", layer 3 spec) —
    marks *all* occurrences of a duplicated key, not just the repeats.
    """
    return key_frame(df, key_columns).duplicated(keep=False)


def unique_keys(df: pd.DataFrame, key_columns: Sequence[str]) -> set:
    """Distinct composite keys present in ``df``."""
    return set(key_frame(df, key_columns))
