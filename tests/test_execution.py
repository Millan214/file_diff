"""Tests for src/utils/execution.py (ExecutionContext, manifest writer)."""

from __future__ import annotations

import json
from datetime import datetime

import pandas as pd
import pytest

from src.utils.execution import LAYER_NAMES, ExecutionContext, LayerResult


def test_create_makes_folder_and_layer_subfolders(make_config):
    config = make_config()
    ctx = ExecutionContext.create(config, now=datetime(2026, 7, 18, 12, 0, 0))

    assert ctx.execution_id == "execution=2026-07-18_12-00-00"
    assert ctx.execution_dir.is_dir()
    assert set(ctx.layer_dirs) == set(LAYER_NAMES)
    for layer_name in LAYER_NAMES:
        assert (ctx.execution_dir / layer_name).is_dir()


def test_collision_appends_suffix_then_increments(make_config):
    config = make_config()
    now = datetime(2026, 7, 18, 12, 0, 0)

    first = ExecutionContext.create(config, now=now)
    second = ExecutionContext.create(config, now=now)
    third = ExecutionContext.create(config, now=now)

    assert first.execution_id == "execution=2026-07-18_12-00-00"
    assert second.execution_id == "execution=2026-07-18_12-00-00_1"
    assert third.execution_id == "execution=2026-07-18_12-00-00_2"
    # All three folders genuinely exist side by side.
    assert first.execution_dir.is_dir()
    assert second.execution_dir.is_dir()
    assert third.execution_dir.is_dir()


def test_input_hash_is_8_char_hex_and_content_sensitive(make_config, fixtures_dir):
    identical_ctx = ExecutionContext.create(
        make_config(
            left=fixtures_dir / "identical_left.csv",
            right=fixtures_dir / "identical_right.csv",
        )
    )
    value_drift_ctx = ExecutionContext.create(
        make_config(
            left=fixtures_dir / "value_drift_left.csv",
            right=fixtures_dir / "value_drift_right.csv",
        )
    )

    assert len(identical_ctx.input_hash) == 8
    int(identical_ctx.input_hash, 16)  # raises if not hex
    # Different input content -> different hash.
    assert identical_ctx.input_hash != value_drift_ctx.input_hash

    # Deterministic: hashing the same pair twice gives the same digest.
    repeat_ctx = ExecutionContext.create(
        make_config(
            left=fixtures_dir / "identical_left.csv",
            right=fixtures_dir / "identical_right.csv",
        )
    )
    assert repeat_ctx.input_hash == identical_ctx.input_hash


def test_input_hash_missing_file_does_not_crash(make_config, tmp_path):
    config = make_config(
        left=tmp_path / "does_not_exist_left.csv",
        right=tmp_path / "does_not_exist_right.csv",
    )
    ctx = ExecutionContext.create(config)  # must not raise
    assert len(ctx.input_hash) == 8


def test_exit_code_zero_when_all_layers_succeed(make_config):
    ctx = ExecutionContext.create(make_config())
    df = pd.DataFrame({"a": [1]})
    for layer_name in LAYER_NAMES:
        ctx.record(LayerResult(name=layer_name, verdict="success", data=df))

    assert ctx.exit_code() == 0


@pytest.mark.parametrize(
    "verdicts,expected_exit_code",
    [
        (["failed", None, None, None], 1),
        (["success", "completed-with-differences", None, None], 2),
        (["success", "success", "completed-with-differences", "success"], 3),
        (["success", "success", "success", "failed"], 4),
    ],
)
def test_exit_code_is_first_non_success_layer(make_config, verdicts, expected_exit_code):
    """D11: exit code = first layer whose verdict != success.

    ``completed-with-differences`` counts as non-success for the exit code
    even though the pipeline gate continues past it (D1/D5) — layer 3 here
    (index 2, 'completed-with-differences') still yields exit code 3 even
    though layer 4 went on to succeed.
    """
    ctx = ExecutionContext.create(make_config())
    df = pd.DataFrame({"a": [1]})
    for layer_name, verdict in zip(LAYER_NAMES, verdicts):
        if verdict is None:
            continue
        ctx.record(LayerResult(name=layer_name, verdict=verdict, data=df))

    assert ctx.exit_code() == expected_exit_code


def test_write_manifest_schema(make_config):
    ctx = ExecutionContext.create(make_config(), now=datetime(2026, 7, 18, 12, 0, 0))
    df = pd.DataFrame({"a": [1, 2]})

    ctx.record(
        LayerResult(
            name="layer_1_read",
            verdict="success",
            data=df,
            extras={
                "summary": {"rows_left": 100, "rows_right": 101},
                "files": {
                    "left": {"path": "data/input/file1.csv", "encoding": "utf-8"},
                    "right": {"path": "data/input/file2.csv", "encoding": "utf-8"},
                },
            },
        )
    )
    ctx.record(
        LayerResult(
            name="layer_3_compare_rows",
            verdict="completed-with-differences",
            data=df,
            extras={
                "summary": {
                    "left_only": 2,
                    "inner": 98,
                    "right_only": 3,
                    "duplicates": 1,
                }
            },
        )
    )

    manifest_path = ctx.write_manifest()
    assert manifest_path.name == "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["execution_id"] == "execution=2026-07-18_12-00-00"
    assert manifest["created"] == "2026-07-18T12:00:00"
    assert len(manifest["input_hash"]) == 8
    assert manifest["files"] == {
        "left": {"path": "data/input/file1.csv", "encoding": "utf-8"},
        "right": {"path": "data/input/file2.csv", "encoding": "utf-8"},
    }
    # layer_3 is completed-with-differences and is the first non-success
    # layer recorded -> exit code reflects layer 3's position.
    assert manifest["exit_code"] == 3

    assert manifest["layers"]["layer_1_read"] == {
        "verdict": "success",
        "csv": "layer_1_read/layer_1_read.csv",
        "summary": {"rows_left": 100, "rows_right": 101},
    }
    assert manifest["layers"]["layer_3_compare_rows"]["summary"] == {
        "left_only": 2,
        "inner": 98,
        "right_only": 3,
        "duplicates": 1,
    }
    # Layers never run are simply absent (dashboard renders them grey).
    assert "layer_2_compare_columns" not in manifest["layers"]
    assert "layer_4_compare_values" not in manifest["layers"]


def test_write_manifest_files_fallback_when_layer1_not_run(make_config):
    config = make_config(left="data/input/file1.csv", right="data/input/file2.csv")
    ctx = ExecutionContext.create(config)
    ctx.write_manifest()

    manifest = json.loads((ctx.execution_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["files"]["left"]["encoding"] is None
    assert manifest["files"]["right"]["encoding"] is None
    assert manifest["files"]["left"]["path"] == "data/input/file1.csv"


def test_write_manifest_rebuilds_executions_index_newest_first(make_config, tmp_path):
    config_early = make_config(output_root=tmp_path)
    ctx_early = ExecutionContext.create(config_early, now=datetime(2026, 7, 18, 9, 0, 0))
    ctx_early.record(
        LayerResult(name="layer_1_read", verdict="success", data=pd.DataFrame({"a": [1]}))
    )
    ctx_early.write_manifest()

    config_late = make_config(output_root=tmp_path)
    ctx_late = ExecutionContext.create(config_late, now=datetime(2026, 7, 18, 15, 0, 0))
    ctx_late.record(
        LayerResult(name="layer_1_read", verdict="failed", data=pd.DataFrame({"a": [1]}))
    )
    ctx_late.write_manifest()

    index = json.loads((tmp_path / "executions.json").read_text(encoding="utf-8"))
    assert [entry["id"] for entry in index] == [
        ctx_late.execution_id,
        ctx_early.execution_id,
    ]
    assert index[0]["exit_code"] == 1
    assert index[1]["exit_code"] == 0
