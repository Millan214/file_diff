"""Layer 4 accepted-differences policy (the only input-load I/O in this layer).

Reads ``config.ACCEPTED_DIFFERENCES_PATH`` -- an input load analogous to layer
1 reading its inputs. Missing/empty/malformed all resolve to "nothing
accepted" with an explanatory note (layer spec: "not an error; log it in the
report") rather than raising.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class AcceptedDifferences:
    """Parsed ``accepted_differences.csv`` (``column, reason, example_*``).

    ``columns`` is the ordered, de-duplicated accepted column set; ``reasons``
    maps each to its reason string (for the PDF's under-chart list and the
    dashboard popup); ``note`` is a human-readable line about where the policy
    came from -- always surfaced in the report so a missing/empty file is
    logged, per the layer spec, rather than silently meaning "nothing accepted".
    """

    columns: tuple[str, ...]
    reasons: dict[str, str]
    note: str


def load_accepted_differences(path: Any) -> AcceptedDifferences:
    """Read the accepted-differences policy; missing/empty = nothing accepted.

    Never raises: an absent, unreadable, header-only, or malformed file all
    resolve to "nothing accepted" with an explanatory ``note`` (layer spec:
    "not an error; log it in the report").
    """
    if path is None:
        return AcceptedDifferences((), {}, "No accepted-differences file configured; nothing is accepted.")

    path = Path(path)
    if not path.is_file():
        return AcceptedDifferences(
            (), {}, f"No accepted-differences file at {path.as_posix()}; nothing is accepted."
        )

    try:
        df = pd.read_csv(path)
    except (pd.errors.EmptyDataError, pd.errors.ParserError, OSError, UnicodeDecodeError):
        return AcceptedDifferences(
            (), {}, f"Accepted-differences file {path.as_posix()} is empty or unreadable; nothing is accepted."
        )

    if df.empty or "column" not in df.columns:
        return AcceptedDifferences(
            (), {}, f"Accepted-differences file {path.as_posix()} lists no accepted columns; nothing is accepted."
        )

    has_reason = "reason" in df.columns
    columns: list[str] = []
    reasons: dict[str, str] = {}
    for _, row in df.iterrows():
        raw = row["column"]
        if pd.isna(raw):
            continue
        column = str(raw).strip()
        if not column:
            continue
        if column not in reasons:
            columns.append(column)
        reason_value = row["reason"] if has_reason else None
        reasons[column] = "" if (reason_value is None or pd.isna(reason_value)) else str(reason_value).strip()

    if not columns:
        return AcceptedDifferences(
            (), {}, f"Accepted-differences file {path.as_posix()} lists no accepted columns; nothing is accepted."
        )
    return AcceptedDifferences(
        tuple(columns), reasons, f"Loaded {len(columns)} accepted column(s) from {path.as_posix()}."
    )
