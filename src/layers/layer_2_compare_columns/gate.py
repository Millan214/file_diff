"""Layer 2 gate -- decide whether to continue (architecture.md's layer contract).

No I/O here: verdict in, decision out.
"""

from __future__ import annotations

from typing import Literal

from src.utils.execution import Verdict

GateDecision = Literal["CONTINUE", "STOP"]


def decide(verdict: Verdict) -> GateDecision:
    """STOP only on a ``failed`` verdict -- common columns empty or a
    configured key column (D2) missing from them. ``completed-with-differences``
    and ``success`` both continue to layer 3 (D5)."""
    return "STOP" if verdict == "failed" else "CONTINUE"
