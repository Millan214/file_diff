"""Layer 1 -- read files, detect encodings, and hard-gate the pipeline.

Public surface for the orchestrator and tests. The layer is split into
``logic`` (pure computation), ``run`` (assembles the ``LayerResult``), and
``output`` (CSV/TXT/PDF I/O); this module just re-exports what they expose.
"""

from __future__ import annotations

from .logic import (
    LAYER_NAME,
    SideResult,
    _read_side,
    check_exists,
    detect_file_encoding,
    load_csv,
    normalize_encoding,
)
from .output import export, report
from .run import run

__all__ = [
    "LAYER_NAME",
    "SideResult",
    "check_exists",
    "detect_file_encoding",
    "export",
    "load_csv",
    "normalize_encoding",
    "report",
    "run",
    "_read_side",
]
