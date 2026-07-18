"""ExecutionContext, manifest writer.

This module owns the pipeline-wide plumbing described in
``.claude/docs/architecture.md`` and ``.claude/docs/dashboard.md``:

- The ``LayerResult`` dataclass every layer's ``run`` phase returns.
- ``ExecutionContext``, which creates the ``data/execution=<ts>/`` folder
  (+ layer subfolders, D10), accumulates each layer's ``LayerResult``, and
  writes ``manifest.json`` + rebuilds the root ``data/executions.json`` index.

Contract for layer authors (see dashboard.md's manifest schema):
- Every ``LayerResult.extras`` may carry a ``"summary"`` dict; its contents
  are copied verbatim into ``manifest["layers"][name]["summary"]`` for the
  dashboard's charts/tables.
- ``layer_1_read``'s ``LayerResult.extras`` should additionally carry a
  ``"files"`` dict shaped exactly like the manifest's top-level ``"files"``
  key (``{"left": {"path": ..., "encoding": ...}, "right": {...}}``) since
  layer 1 is the only layer that reads the input files and detects
  encoding. If layer 1 has not run yet, ``write_manifest`` falls back to
  the configured input paths with ``encoding: None``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import pandas as pd

Verdict = Literal["success", "completed-with-differences", "failed"]

#: Canonical layer order, used for folder creation, exit-code computation
#: (D11), and manifest ordering. Names match the ``src/layers/`` package
#: names and the manifest.json / dashboard.md layer keys exactly.
LAYER_NAMES: tuple[str, ...] = (
    "layer_1_read",
    "layer_2_compare_columns",
    "layer_3_compare_rows",
    "layer_4_compare_values",
)

_TIMESTAMP_FORMAT = "%Y-%m-%d_%H-%M-%S"


@dataclass
class LayerResult:
    """What a layer's ``run`` phase produces (architecture.md's layer contract).

    ``extras`` is a free-form dict for layer-specific data that export/report
    need (e.g. duplicate key lists, dtype tables) plus the dashboard-facing
    ``"summary"`` dict (see module docstring).
    """

    name: str
    verdict: Verdict
    data: pd.DataFrame
    extras: dict[str, Any] = field(default_factory=dict)


def _hash_inputs(left_path: Path, right_path: Path) -> str:
    """8-char SHA-256 content hash of both input files (D10).

    Falls back to hashing the path string when a file cannot be read so
    that a missing input (which layer 1 is responsible for reporting as a
    ``failed`` verdict) never crashes execution-context setup.
    """
    hasher = hashlib.sha256()
    for path in (left_path, right_path):
        try:
            hasher.update(Path(path).read_bytes())
        except OSError:
            hasher.update(str(path).encode("utf-8"))
    return hasher.hexdigest()[:8]


def _resolve_execution_dir(output_root: Path, timestamp: str) -> tuple[str, Path]:
    """Pick a free ``execution=<timestamp>[_N]`` id (D10: ``_1`` on collision)."""
    base_id = f"execution={timestamp}"
    candidate_id = base_id
    counter = 0
    while (output_root / candidate_id).exists():
        counter += 1
        candidate_id = f"{base_id}_{counter}"
    return candidate_id, output_root / candidate_id


def _rebuild_executions_index(output_root: Path) -> Path:
    """Rebuild ``data/executions.json`` by scanning ``execution=*`` folders.

    Entries are ``{"id", "date", "exit_code"}``, newest first (by the
    manifest's ``created`` timestamp). Folders without a readable
    manifest.json are skipped rather than failing the whole run.
    """
    entries: list[dict[str, Any]] = []
    if output_root.exists():
        for child in output_root.iterdir():
            if not child.is_dir() or not child.name.startswith("execution="):
                continue
            manifest_path = child / "manifest.json"
            if not manifest_path.exists():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            entries.append(
                {
                    "id": manifest.get("execution_id", child.name),
                    "date": manifest.get("created", ""),
                    "exit_code": manifest.get("exit_code", -1),
                }
            )
    entries.sort(key=lambda e: e["date"], reverse=True)

    index_path = output_root / "executions.json"
    index_path.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    return index_path


@dataclass
class ExecutionContext:
    """Holds config, the execution folder layout, and per-layer results.

    Construct via :meth:`create` (never the bare constructor) so the folder
    layout and input hash are always set up consistently.
    """

    config: Any
    output_root: Path
    execution_id: str
    execution_dir: Path
    created_at: datetime
    input_hash: str
    layer_dirs: dict[str, Path]
    results: dict[str, LayerResult] = field(default_factory=dict)

    @classmethod
    def create(cls, config: Any, now: datetime | None = None) -> "ExecutionContext":
        """Create the execution folder tree and return a fresh context.

        ``now`` is injectable for deterministic tests (e.g. to force a
        same-second collision and exercise the ``_1`` suffix, D10).
        """
        now = now or datetime.now()
        output_root = Path(config.DATA_OUTPUT_ROOT)
        output_root.mkdir(parents=True, exist_ok=True)

        timestamp = now.strftime(_TIMESTAMP_FORMAT)
        execution_id, execution_dir = _resolve_execution_dir(output_root, timestamp)
        execution_dir.mkdir(parents=True, exist_ok=False)

        layer_dirs = {}
        for layer_name in LAYER_NAMES:
            layer_dir = execution_dir / layer_name
            layer_dir.mkdir(parents=True, exist_ok=True)
            layer_dirs[layer_name] = layer_dir

        input_hash = _hash_inputs(Path(config.INPUT_LEFT), Path(config.INPUT_RIGHT))

        return cls(
            config=config,
            output_root=output_root,
            execution_id=execution_id,
            execution_dir=execution_dir,
            created_at=now,
            input_hash=input_hash,
            layer_dirs=layer_dirs,
        )

    def layer_dir(self, layer_name: str) -> Path:
        return self.layer_dirs[layer_name]

    def csv_path(self, layer_name: str) -> Path:
        return self.layer_dir(layer_name) / f"{layer_name}.csv"

    def txt_path(self, layer_name: str) -> Path:
        return self.layer_dir(layer_name) / f"{layer_name}.txt"

    def pdf_path(self, layer_name: str) -> Path:
        return self.layer_dir(layer_name) / f"{layer_name}.pdf"

    def record(self, result: LayerResult) -> None:
        """Store a layer's result, keyed by its name."""
        self.results[result.name] = result

    def exit_code(self) -> int:
        """D11: number of the first layer whose verdict was not ``success``.

        ``completed-with-differences`` counts as "not success" here even
        though the pipeline gate continues past it (D1/D5) — the exit code
        is a compact summary, not the full story; per-layer verdicts in the
        manifest carry the detail.
        """
        for position, layer_name in enumerate(LAYER_NAMES, start=1):
            result = self.results.get(layer_name)
            if result is None:
                continue
            if result.verdict != "success":
                return position
        return 0

    def _relative(self, path: Path) -> str:
        return path.relative_to(self.execution_dir).as_posix()

    def manifest_dict(self) -> dict[str, Any]:
        layer_1 = self.results.get("layer_1_read")
        if layer_1 is not None and "files" in layer_1.extras:
            files = layer_1.extras["files"]
        else:
            files = {
                "left": {"path": Path(self.config.INPUT_LEFT).as_posix(), "encoding": None},
                "right": {"path": Path(self.config.INPUT_RIGHT).as_posix(), "encoding": None},
            }

        layers: dict[str, Any] = {}
        for layer_name, result in self.results.items():
            layers[layer_name] = {
                "verdict": result.verdict,
                "csv": self._relative(self.csv_path(layer_name)),
                "summary": result.extras.get("summary", {}),
            }

        return {
            "execution_id": self.execution_id,
            "created": self.created_at.isoformat(timespec="seconds"),
            "input_hash": self.input_hash,
            "files": files,
            "exit_code": self.exit_code(),
            "layers": layers,
        }

    def write_manifest(self) -> Path:
        """Write ``manifest.json`` and rebuild ``data/executions.json``."""
        manifest_path = self.execution_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(self.manifest_dict(), indent=2), encoding="utf-8"
        )
        _rebuild_executions_index(self.output_root)
        return manifest_path
