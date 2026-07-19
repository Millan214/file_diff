"""Layer 3 ``run`` -- assemble the row classification into a LayerResult.

Pure orchestration over layer 1's DataFrames and ``config.KEY_COLUMNS``
(composite-safe via ``src/utils/keys.py``); no I/O (see ``output.py``).
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.utils.execution import LayerResult
from src.utils.keys import key_frame, unique_keys

from .logic import (
    _INNER,
    LAYER_NAME,
    _build_export_frame,
    _build_summary,
    classify_keys,
    find_duplicates,
    row_verdict,
)


def run(layer1_result: LayerResult, layer2_result: LayerResult, config: Any) -> LayerResult:
    """Classify df_left/df_right rows by ``config.KEY_COLUMNS`` (D2, composite-safe).

    ``layer2_result.extras["common_columns"]`` is accepted for interface
    parity with the other layers' ``run(layer_n_result, ..., config)``
    signatures, but row pairing here is purely a function of the key
    columns -- it is not otherwise used: layer 2 already guarantees the key
    columns are a subset of the common set (D2) by the time layer 3 runs, so
    there is nothing left for layer 3 to validate against it.
    """
    df_left: pd.DataFrame = layer1_result.extras["df_left"]
    df_right: pd.DataFrame = layer1_result.extras["df_right"]
    _common_columns = layer2_result.extras["common_columns"]  # noqa: F841 (see docstring)
    key_columns = list(config.KEY_COLUMNS)

    left_keys = unique_keys(df_left, key_columns)
    right_keys = unique_keys(df_right, key_columns)
    dup_left_keys = find_duplicates(df_left, key_columns)
    dup_right_keys = find_duplicates(df_right, key_columns)

    classification = classify_keys(left_keys, right_keys, dup_left_keys, dup_right_keys)
    verdict = row_verdict(classification)

    kf_left = key_frame(df_left, key_columns)
    kf_right = key_frame(df_right, key_columns)
    data = _build_export_frame(df_left, df_right, key_columns, classification, kf_left, kf_right)
    summary = _build_summary(classification, dup_left_keys, dup_right_keys)

    extras = {
        "inner_keys": classification[_INNER],
        "summary": summary,
        "key_columns": key_columns,
    }
    return LayerResult(name=LAYER_NAME, verdict=verdict, data=data, extras=extras)
