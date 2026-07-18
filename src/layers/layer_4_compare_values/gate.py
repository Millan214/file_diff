"""Layer 4 gate -- the terminal gate (architecture.md's layer contract).

No I/O: verdict in, decision out. Layer 4 is the last layer, so the decision
does not gate a next layer -- the pipeline's real outcome is the exit code
(``ExecutionContext.exit_code``: ``failed`` here -> exit 4, D11). ``STOP`` on
``failed`` is kept only for uniformity with the earlier gates.
"""

from __future__ import annotations

from typing import Literal

from src.utils.execution import Verdict

GateDecision = Literal["CONTINUE", "STOP"]


def decide(verdict: Verdict) -> GateDecision:
    """``STOP`` on ``failed`` (non-accepted value differences), else ``CONTINUE``."""
    return "STOP" if verdict == "failed" else "CONTINUE"
