"""Layer 3 gate -- decide whether to continue.

Trivially small per architecture.md's contract: verdict in, decision out,
no I/O. Layer 3 always CONTINUEs even with row differences (D1) -- ``STOP``
is reserved for ``failed``, which ``compare_rows.row_verdict`` only produces
when the inner key set is empty (nothing left for layer 4 to compare).
"""

from __future__ import annotations

from typing import Literal

from src.utils.execution import Verdict

GateDecision = Literal["CONTINUE", "STOP"]


def decide(verdict: Verdict) -> GateDecision:
    """``STOP`` only on ``failed``; ``CONTINUE`` otherwise (D1)."""
    return "STOP" if verdict == "failed" else "CONTINUE"
