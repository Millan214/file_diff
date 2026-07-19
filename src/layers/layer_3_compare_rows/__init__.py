"""Layer 3 -- match rows by key and find duplicates.

Public surface for the orchestrator and tests. Split into ``logic`` (pure
computation), ``run`` (assembles the ``LayerResult``), and ``output`` (CSV/
TXT/PDF I/O); this module re-exports what they expose.
"""

from __future__ import annotations

from .logic import LAYER_NAME, classify_keys, find_duplicates, row_verdict
from .output import export, report
from .run import run

__all__ = [
    "LAYER_NAME",
    "classify_keys",
    "export",
    "find_duplicates",
    "report",
    "row_verdict",
    "run",
]
