"""Layer 4 -- cell-by-cell value comparison + accepted-differences policy.

Public surface for the orchestrator and tests. Split into ``equality`` (the D9
value-equality matrix), ``accepted`` (the policy loader), ``logic`` (the
align/compare/flag/verdict transforms + summary), ``run`` (assembles the
``LayerResult``), and ``output`` (CSV/TXT/PDF I/O); this module re-exports what
they expose.
"""

from __future__ import annotations

from .accepted import AcceptedDifferences, load_accepted_differences
from .equality import values_equal
from .logic import LAYER_NAME, align_frames, compare_cells, flag_accepted, value_verdict
from .output import export, report
from .run import run

__all__ = [
    "AcceptedDifferences",
    "LAYER_NAME",
    "align_frames",
    "compare_cells",
    "export",
    "flag_accepted",
    "load_accepted_differences",
    "report",
    "run",
    "value_verdict",
    "values_equal",
]
