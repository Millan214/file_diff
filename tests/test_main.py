"""Tests for src/main.py (the orchestrator).

Exercises the full layer_1 -> layer_2 -> layer_3 -> layer_4 pipeline end to
end against real fixture pairs, checking: the run -> export -> report ->
gate contract holds (architecture.md), a STOP decision halts the pipeline
early (later layers simply never appear in the manifest), D11's exit codes,
and crash handling (an unexpected exception still yields a written manifest
with exit code CRASHED_EXIT_CODE, never a bare traceback).
"""

from __future__ import annotations

import json

import pytest

from src.layers import layer_2_compare_columns as layer_2
from src.main import main
from src.utils.execution import CRASHED_EXIT_CODE, LAYER_NAMES


# ---------------------------------------------------------------------------
# local config helper -- make_config (conftest.py) only sets
# DATA_OUTPUT_ROOT/INPUT_LEFT/INPUT_RIGHT; the orchestrator needs the full
# config surface every layer reads (mirrors test_layer_1_read.py's
# read_config / test_layer_4_compare_values.py's _config pattern).
# ---------------------------------------------------------------------------


@pytest.fixture
def pipeline_config(make_config, fixtures_dir):
    def _make(pair: str, *, key_columns=("id",), accepted_path=None):
        config = make_config(
            left=fixtures_dir / f"{pair}_left.csv",
            right=fixtures_dir / f"{pair}_right.csv",
        )
        config.KEY_COLUMNS = list(key_columns)
        config.CSV_DELIMITER = ","
        config.CSV_HEADER_ROW = 0
        config.PER_COLUMN_NUMERIC_TOLERANCE = {}
        config.ACCEPTED_DIFFERENCES_PATH = accepted_path
        return config

    return _make


def _manifest(config) -> dict:
    execution_dirs = [p for p in config.DATA_OUTPUT_ROOT.iterdir() if p.name.startswith("execution=")]
    assert len(execution_dirs) == 1
    return json.loads((execution_dirs[0] / "manifest.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Full pipeline, per fixture pair
# ---------------------------------------------------------------------------


def test_identical_all_layers_succeed(pipeline_config):
    config = pipeline_config("identical")

    exit_code = main(config)

    assert exit_code == 0
    manifest = _manifest(config)
    assert set(manifest["layers"]) == set(LAYER_NAMES)
    for layer_name in LAYER_NAMES:
        assert manifest["layers"][layer_name]["verdict"] == "success"
    assert "crashed" not in manifest


def test_layer1_hard_failure_stops_pipeline_at_layer1(pipeline_config, tmp_path):
    config = pipeline_config("identical")
    config.INPUT_LEFT = tmp_path / "does_not_exist.csv"

    exit_code = main(config)

    assert exit_code == 1
    manifest = _manifest(config)
    assert set(manifest["layers"]) == {"layer_1_read"}
    assert manifest["layers"]["layer_1_read"]["verdict"] == "failed"


def test_empty_common_stops_pipeline_at_layer2(pipeline_config):
    """D5: empty_common has no overlapping columns *and* is missing the
    configured key column -> layer 2 hard-fails, layer 3 never runs."""
    config = pipeline_config("empty_common")

    exit_code = main(config)

    assert exit_code == 2
    manifest = _manifest(config)
    assert set(manifest["layers"]) == {"layer_1_read", "layer_2_compare_columns"}
    assert manifest["layers"]["layer_2_compare_columns"]["verdict"] == "failed"


def test_row_drift_dupes_continues_through_layer4(pipeline_config):
    """D1: layer 3's row differences/duplicates soft-gate -- the pipeline
    still runs layer 4, but the exit code reflects layer 3 (the first
    non-success layer), not layer 4's own (successful) verdict."""
    config = pipeline_config("row_drift_dupes")

    exit_code = main(config)

    assert exit_code == 3
    manifest = _manifest(config)
    assert set(manifest["layers"]) == set(LAYER_NAMES)
    assert manifest["layers"]["layer_3_compare_rows"]["verdict"] == "completed-with-differences"
    assert manifest["layers"]["layer_4_compare_values"]["verdict"] == "success"


def test_value_drift_no_accepted_differences_fails_layer4(pipeline_config):
    config = pipeline_config("value_drift")

    exit_code = main(config)

    assert exit_code == 4
    manifest = _manifest(config)
    assert set(manifest["layers"]) == set(LAYER_NAMES)
    assert manifest["layers"]["layer_4_compare_values"]["verdict"] == "failed"


def test_value_drift_all_accepted_differences_pass(pipeline_config, tmp_path):
    """D3: an accepted-differences policy covering every diff'd column turns
    the same value_drift pair into an exit-code-0 run."""
    accepted_path = tmp_path / "accepted.csv"
    accepted_path.write_text(
        "column,reason,example_left,example_right\n"
        "name,renamed,Bob,Robert\n"
        "value,rounded,200,205\n",
        encoding="utf-8",
    )
    config = pipeline_config("value_drift", accepted_path=accepted_path)

    exit_code = main(config)

    assert exit_code == 0
    manifest = _manifest(config)
    assert manifest["layers"]["layer_4_compare_values"]["verdict"] == "success"


def test_artifacts_written_for_every_recorded_layer(pipeline_config):
    """architecture.md's contract: csv/txt/pdf exist for each layer that ran,
    even the terminal ``failed`` one (value_drift's layer 4)."""
    config = pipeline_config("value_drift")

    main(config)

    execution_dirs = [p for p in config.DATA_OUTPUT_ROOT.iterdir() if p.name.startswith("execution=")]
    execution_dir = execution_dirs[0]
    for layer_name in LAYER_NAMES:
        layer_dir = execution_dir / layer_name
        assert (layer_dir / f"{layer_name}.csv").exists()
        assert (layer_dir / f"{layer_name}.txt").exists()
        assert (layer_dir / f"{layer_name}.pdf").exists()


def test_executions_index_rebuilt(pipeline_config):
    config = pipeline_config("identical")

    main(config)

    index = json.loads((config.DATA_OUTPUT_ROOT / "executions.json").read_text(encoding="utf-8"))
    assert len(index) == 1
    assert index[0]["exit_code"] == 0


# ---------------------------------------------------------------------------
# Crash handling
# ---------------------------------------------------------------------------


def test_unexpected_exception_is_caught_and_manifest_still_written(pipeline_config, monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(layer_2, "run", _boom)
    config = pipeline_config("identical")

    exit_code = main(config)

    assert exit_code == CRASHED_EXIT_CODE
    manifest = _manifest(config)
    assert manifest["crashed"] is True
    assert "disk full" in manifest["error"]
    assert manifest["exit_code"] == CRASHED_EXIT_CODE
    # Layer 1 completed before the crash and is still recorded; layer 2 (where
    # the crash happened, before it could return a LayerResult) is not.
    assert manifest["layers"]["layer_1_read"]["verdict"] == "success"
    assert "layer_2_compare_columns" not in manifest["layers"]
