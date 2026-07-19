"""Layer 1 ``run`` -- assemble the pure per-side steps into a LayerResult.

Loads both configured input files (via ``logic._read_side``), applies the
cross-file encoding-compatibility check, and hard-gates on any failure. The
computation itself is pure; the only I/O is inside ``logic.load_csv`` /
``logic.detect_file_encoding``. Exports/reports live in ``output.py``.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.utils.execution import LayerResult, Verdict

from .logic import (
    LAYER_NAME,
    _EXPORT_COLUMNS,
    _failure_reasons,
    _mark_encoding_mismatch,
    _read_side,
    _side_row,
)


def run(config: Any) -> LayerResult:
    """Load both configured input files and hard-gate on any failure (layer 1 spec)."""
    left = _read_side(
        "left", config.INPUT_LEFT, delimiter=config.CSV_DELIMITER, header_row=config.CSV_HEADER_ROW
    )
    right = _read_side(
        "right", config.INPUT_RIGHT, delimiter=config.CSV_DELIMITER, header_row=config.CSV_HEADER_ROW
    )
    left, right = _mark_encoding_mismatch(left, right)

    both_loaded = (
        left.status == "ok" and right.status == "ok" and left.df is not None and right.df is not None
    )
    verdict: Verdict = "success" if both_loaded else "failed"

    data = pd.DataFrame([_side_row(left), _side_row(right)], columns=_EXPORT_COLUMNS)

    extras: dict[str, Any] = {
        "df_left": left.df,
        "df_right": right.df,
        "left_encoding": left.encoding_normalized,
        "right_encoding": right.encoding_normalized,
        "files": {
            "left": {"path": left.path.as_posix(), "encoding": left.encoding_normalized},
            "right": {"path": right.path.as_posix(), "encoding": right.encoding_normalized},
        },
        "summary": {
            "rows_left": len(left.df) if left.df is not None else None,
            "rows_right": len(right.df) if right.df is not None else None,
            "columns_left": len(left.df.columns) if left.df is not None else None,
            "columns_right": len(right.df.columns) if right.df is not None else None,
        },
        "failure_reasons": _failure_reasons(left, right) if verdict == "failed" else [],
    }

    return LayerResult(name=LAYER_NAME, verdict=verdict, data=data, extras=extras)
