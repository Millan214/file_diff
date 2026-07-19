"""Layer 4 value equality -- the D9 comparison matrix.

This is where the subtle correctness lives: whether two cell values count as
equal (NaN==NaN, numeric coercion with optional per-column tolerance, else
trailing-whitespace-stripped string equality). Pure and self-contained so
``logic.compare_cells`` can build on it without pulling in the rest of the
layer.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


def _is_na(value: object) -> bool:
    """Missing test that never raises on array-like/odd inputs.

    ``pd.isna`` returns an array for array-likes; layer 4 only ever passes
    scalars, but the guard keeps a stray object from turning a comparison
    into a truth-value-of-an-array error.
    """
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _as_number(value: object) -> float | None:
    """Return ``value`` as a finite ``float`` when it *is* a number or a numeric
    string, else ``None`` (D9's "both sides parse as numeric" test).

    Booleans are deliberately not numbers here (``True`` must not equal ``1``),
    and non-finite results (``inf``/``nan`` from a literal string) fall back to
    string comparison so e.g. two ``"nan"`` strings compare equal instead of
    NaN-comparing unequal to themselves.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, np.integer, np.floating)):
        number = float(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
    else:
        return None
    return number if math.isfinite(number) else None


def _as_text(value: object) -> str:
    """String form for the fallback comparison, trailing whitespace stripped (D9)."""
    return ("" if value is None else str(value)).rstrip()


def values_equal(left: object, right: object, tolerance: float = 0.0) -> bool:
    """Are two cell values equal under D9?

    1. Both missing -> equal (NaN==NaN is True). Exactly one missing -> not equal.
    2. Both parse as numbers -> equal iff ``abs(left-right) <= tolerance``
       (default ``0`` = exact, so ``1 == 1.0`` but ``200 != 205``).
    3. Otherwise -> equal iff the strings match after stripping trailing
       whitespace (dates are compared as text, not format-normalized).
    """
    left_na, right_na = _is_na(left), _is_na(right)
    if left_na or right_na:
        return left_na and right_na

    left_num, right_num = _as_number(left), _as_number(right)
    if left_num is not None and right_num is not None:
        return abs(left_num - right_num) <= tolerance

    return _as_text(left) == _as_text(right)
