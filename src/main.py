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


def _run_one_layer(
    ctx: ExecutionContext,
    run: Callable[..., Any],
    export: Callable[..., None],
    report: Callable[..., None],
    gate: Any,
    *run_args: Any,
) -> str:
    """``run -> record -> export -> report -> gate.decide``, in that fixed order."""
    result = run(*run_args)
    ctx.record(result)
    export(result, ctx)
    report(result, ctx)
    return gate.decide(result.verdict)


def run_pipeline(ctx: ExecutionContext) -> None:
    """Drive layers 1-4 in order, stopping early on any ``STOP`` gate decision."""
    config = ctx.config

    decision = _run_one_layer(
        ctx, layer_1.run, layer_1.export, layer_1.report, layer_1_gate, config
    )
    if decision == "STOP":
        return
    result_1 = ctx.results["layer_1_read"]

    decision = _run_one_layer(
        ctx, layer_2.run, layer_2.export, layer_2.report, layer_2_gate, result_1, config
    )
    if decision == "STOP":
        return
    result_2 = ctx.results["layer_2_compare_columns"]

    decision = _run_one_layer(
        ctx,
        layer_3.run,
        layer_3.export,
        layer_3.report,
        layer_3_gate,
        result_1,
        result_2,
        config,
    )
    if decision == "STOP":
        return
    result_3 = ctx.results["layer_3_compare_rows"]

    _run_one_layer(
        ctx,
        layer_4.run,
        layer_4.export,
        layer_4.report,
        layer_4_gate,
        result_1,
        result_2,
        result_3,
        config,
    )


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


if __name__ == "__main__":
    sys.exit(main())
