"""Layer 2 -- compare column sets and dtypes.

Public surface for the orchestrator and tests. Split into ``logic`` (pure
computation), ``run`` (assembles the ``LayerResult``), and ``output`` (CSV/
TXT/PDF I/O); this module re-exports what they expose.
"""

from __future__ import annotations

from .logic import LAYER_NAME, build_column_report, column_verdict, dtype_table, split_columns
from .output import export, report
from .run import run

__all__ = [
    "LAYER_NAME",
    "build_column_report",
    "column_verdict",
    "dtype_table",
    "export",
    "report",
    "run",
    "split_columns",
]
