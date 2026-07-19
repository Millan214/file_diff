"""Layer 4 ``run`` -- assemble the value comparison into a LayerResult.

Consumes layer 1's DataFrames, layer 2's ``common_columns``, and layer 3's
``inner_keys`` (architecture.md's layer inputs table); applies the
accepted-differences policy. This is the terminal layer -- its verdict drives
exit code 4 (D11). No file writing here (see ``output.py``).
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.utils.execution import LayerResult

from .accepted import load_accepted_differences
from .logic import (
    LAYER_NAME,
    _build_summary,
    align_frames,
    compare_cells,
    flag_accepted,
    value_verdict,
)


def run(
    layer1_result: LayerResult,
    layer2_result: LayerResult,
    layer3_result: LayerResult,
    config: Any,
) -> LayerResult:
    """Compare inner rows x common columns and apply the accepted-differences policy."""
    df_left: pd.DataFrame = layer1_result.extras["df_left"]
    df_right: pd.DataFrame = layer1_result.extras["df_right"]
    common_columns = list(layer2_result.extras["common_columns"])
    inner_keys: set = layer3_result.extras["inner_keys"]
    key_columns = list(config.KEY_COLUMNS)
    tolerances = dict(getattr(config, "PER_COLUMN_NUMERIC_TOLERANCE", {}) or {})

    left_aligned, right_aligned = align_frames(
        df_left, df_right, common_columns, key_columns, inner_keys
    )
    accepted = load_accepted_differences(getattr(config, "ACCEPTED_DIFFERENCES_PATH", None))

    diff_table = compare_cells(
        left_aligned, right_aligned, common_columns, key_columns, tolerances
    ).pipe(flag_accepted, accepted.columns)
    verdict = value_verdict(diff_table)

    compare_columns = [c for c in common_columns if c not in set(key_columns)]
    summary = _build_summary(diff_table, compare_columns, len(left_aligned), accepted)

    extras = {
        "summary": summary,
        "accepted": {
            "columns": list(accepted.columns),
            "reasons": accepted.reasons,
            "note": accepted.note,
        },
        "compared_columns": compare_columns,
        "key_columns": key_columns,
    }
    return LayerResult(name=LAYER_NAME, verdict=verdict, data=diff_table, extras=extras)
