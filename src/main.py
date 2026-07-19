"""Orchestrator for the compare-dataframes pipeline (architecture.md).

Runs the four layers in order, each through its fixed ``run -> export ->
report -> gate`` contract (architecture.md's layer contract): artifacts are
always written before the gate decides, including on a failing verdict. A
``STOP`` decision ends the pipeline early -- downstream layers are simply
never recorded, which the dashboard renders as "not run" (grey, dashboard.md).

Crash handling: an unexpected exception from any layer's ``run``/``export``/
``report`` escapes here rather than being mistaken for a normal ``failed``
verdict. It stops the pipeline immediately; ``manifest.json`` is still
written for whatever layers completed (architecture.md's error-handling
section), with a top-level ``crashed``/``error`` pair and exit code
``CRASHED_EXIT_CODE`` (src/utils/execution.py), which can never collide with
a D11 layer-position code.
"""

from __future__ import annotations

import sys
import traceback
from dataclasses import dataclass
from typing import Any, Callable

from src.config import config as default_config
from src.layers.layer_1_read import gate as layer_1_gate
from src.layers.layer_1_read import read as layer_1
from src.layers.layer_2_compare_columns import compare_columns as layer_2
from src.layers.layer_2_compare_columns import gate as layer_2_gate
from src.layers.layer_3_compare_rows import compare_rows as layer_3
from src.layers.layer_3_compare_rows import gate as layer_3_gate
from src.layers.layer_4_compare_values import compare_values as layer_4
from src.layers.layer_4_compare_values import gate as layer_4_gate
from src.utils.execution import ExecutionContext


def main(config: Any = default_config) -> int:
    """Create an execution, run the pipeline, always write the manifest, return the exit code."""
    ctx = ExecutionContext.create(config)
    try:
        run_pipeline(ctx)
    except Exception as exc:  # noqa: BLE001 -- deliberately broad, see module docstring
        traceback.print_exc()
        ctx.mark_crashed(f"{type(exc).__name__}: {exc}")
    ctx.write_manifest()
    return ctx.exit_code()


def run_pipeline(ctx: ExecutionContext) -> None:
    """Run each layer in order, stopping early on any ``STOP`` gate decision."""
    try:
        for module, gate in _LAYERS:
            _run_one_layer(ctx, _LayerStage.of(module, gate))
    except _StopPipeline:
        pass


def _run_one_layer(ctx: ExecutionContext, stage: _LayerStage) -> None:
    """``run -> export -> report -> record -> gate.decide``, in that fixed order.

    A layer's ``run`` receives every result recorded so far, in order, plus
    the config (architecture.md's layer inputs table). ``record`` runs only
    after both artifacts are on disk, so a crash during ``export``/``report``
    leaves the layer *unrecorded* rather than pointing ``manifest.json`` at a
    file that was never written. Raises ``_StopPipeline`` on a ``STOP``.
    """
    prior_results = tuple(ctx.results.values())
    result = stage.run(*prior_results, ctx.config)
    stage.export(result, ctx)
    stage.report(result, ctx)
    ctx.record(result)
    if stage.decide(result.verdict) == "STOP":
        raise _StopPipeline()


@dataclass
class _LayerStage:
    """One layer's ``run``/``export``/``report`` phase plus its gate ``decide``."""

    run: Callable[..., Any]
    export: Callable[..., None]
    report: Callable[..., None]
    decide: Callable[..., str]

    @classmethod
    def of(cls, module: Any, gate: Any) -> _LayerStage:
        """Unpack the four callables from a layer module and its gate module."""
        return cls(module.run, module.export, module.report, gate.decide)


#: The pipeline, in execution order, as ``(layer module, gate module)`` pairs.
#: ``run_pipeline`` walks this table; each layer is fed the results of every
#: layer before it (see ``_run_one_layer``). Pairs (not pre-built stages) so
#: the callables resolve fresh each run -- tests monkeypatch e.g. ``layer_2.run``.
_LAYERS: tuple[tuple[Any, Any], ...] = (
    (layer_1, layer_1_gate),
    (layer_2, layer_2_gate),
    (layer_3, layer_3_gate),
    (layer_4, layer_4_gate),
)


class _StopPipeline(Exception):
    """Signals a ``STOP`` gate decision, unwinding ``run_pipeline`` early."""


if __name__ == "__main__":
    sys.exit(main())
