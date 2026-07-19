"""Orchestrator for the compare-dataframes pipeline (architecture.md).

Runs the four layers in order, each through its fixed ``run -> export ->
report`` contract (architecture.md's layer contract): artifacts are always
written before the pipeline decides whether to continue, including on a
failing verdict. A ``failed`` verdict ends the pipeline early -- downstream
layers are simply never recorded, which the dashboard renders as "not run"
(grey, dashboard.md). Every other verdict continues to the next layer.

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
from typing import Any

from src.config import config as default_config
from src.layers import layer_1_read as layer_1
from src.layers import layer_2_compare_columns as layer_2
from src.layers import layer_3_compare_rows as layer_3
from src.layers import layer_4_compare_values as layer_4
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
    """Run each layer in order, stopping early on the first ``failed`` verdict."""
    for module in _LAYERS:
        if not _run_one_layer(ctx, module):
            return


def _run_one_layer(ctx: ExecutionContext, module: Any) -> bool:
    """``run -> export -> report -> record``, in that fixed order.

    A layer's ``run`` receives every result recorded so far, in order, plus
    the config (architecture.md's layer inputs table). ``record`` runs only
    after both artifacts are on disk, so a crash during ``export``/``report``
    leaves the layer *unrecorded* rather than pointing ``manifest.json`` at a
    file that was never written. Returns ``False`` on a ``failed`` verdict to
    halt the pipeline, ``True`` to continue.
    """
    prior_results = tuple(ctx.results.values())
    result = module.run(*prior_results, ctx.config)
    module.export(result, ctx)
    module.report(result, ctx)
    ctx.record(result)
    return result.verdict != "failed"


#: The pipeline, in execution order. ``run_pipeline`` walks this table; each
#: layer is fed the results of every layer before it (see ``_run_one_layer``).
#: Referenced as modules (not pre-bound callables) so ``run``/``export``/
#: ``report`` resolve fresh each run -- tests monkeypatch e.g. ``layer_2.run``.
_LAYERS: tuple[Any, ...] = (layer_1, layer_2, layer_3, layer_4)


if __name__ == "__main__":
    sys.exit(main())
