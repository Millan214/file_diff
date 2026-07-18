"""Public facade for utilities.

Layer modules and the orchestrator should import from here (or from
``src.utils`` once re-exported in ``__init__.py``) rather than reaching
into the individual submodules directly, so the internal module layout can
change without breaking callers.

"""

from __future__ import annotations

from src.utils.artifacts import write_csv, write_txt
from src.utils.encoding import (
    DetectedEncoding,
    EncodingDetectionError,
    detect_encoding,
    normalize,
)
from src.utils.execution import (
    LAYER_NAMES,
    ExecutionContext,
    LayerResult,
    Verdict,
)
from src.utils.keys import (
    MissingKeyColumnsError,
    duplicate_mask,
    key_frame,
    unique_keys,
)
from src.utils.pdf import ReportBuilder, barh_chart

__all__ = [
    # artifacts.py
    "write_csv",
    "write_txt",
    # encoding.py
    "DetectedEncoding",
    "EncodingDetectionError",
    "detect_encoding",
    "normalize",
    # execution.py
    "LAYER_NAMES",
    "ExecutionContext",
    "LayerResult",
    "Verdict",
    # keys.py
    "MissingKeyColumnsError",
    "duplicate_mask",
    "key_frame",
    "unique_keys",
    # pdf.py
    "ReportBuilder",
    "barh_chart",
]
