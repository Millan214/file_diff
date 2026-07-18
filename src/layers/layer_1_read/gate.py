"""Layer 1 gate -- decide whether to continue.

Layer 1 hard-gates the pipeline (layer_1_read.md's Purpose): any verdict
other than ``"success"`` stops the run (D11: exit code 1). No I/O here --
verdict in, decision out (architecture.md's code style).
"""

from __future__ import annotations

from typing import Literal

from src.utils.execution import Verdict

GateDecision = Literal["CONTINUE", "STOP"]


def decide(verdict: Verdict) -> GateDecision:
    """``failed -> STOP``, otherwise ``CONTINUE``."""
    return "STOP" if verdict == "failed" else "CONTINUE"
