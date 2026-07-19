"""Layer 2 ``run`` -- assemble the column/dtype comparison into a LayerResult.

Pure orchestration over layer 1's two DataFrames; no I/O (see ``output.py``).
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.utils.execution import LayerResult

from .logic import LAYER_NAME, build_column_report, column_verdict, dtype_table, split_columns


def run(layer1_result: LayerResult, config: Any) -> LayerResult:
    """Compare layer 1's two DataFrames' column sets and dtypes."""
    df_left: pd.DataFrame = layer1_result.extras["df_left"]
    df_right: pd.DataFrame = layer1_result.extras["df_right"]
    key_columns = list(getattr(config, "KEY_COLUMNS", []))

    cols = split_columns(df_left, df_right)
    dtypes = dtype_table(df_left, df_right, cols["common"])
    verdict = column_verdict(cols, dtypes, key_columns)
    data = build_column_report(df_left, df_right, cols)

    dtype_mismatches = int((~dtypes["dtype_match"]).sum()) if not dtypes.empty else 0
    summary = {
        "left_only": len(cols["left_only"]),
        "right_only": len(cols["right_only"]),
        "common": len(cols["common"]),
        "dtype_mismatches": dtype_mismatches,
    }

    extras = {
        "common_columns": cols["common"],
        "left_only_columns": cols["left_only"],
        "right_only_columns": cols["right_only"],
        "dtype_table": dtypes,
        "summary": summary,
    }

    return LayerResult(name=LAYER_NAME, verdict=verdict, data=data, extras=extras)
