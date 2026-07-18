"""Tests for src/layers/layer_1_read (read.py + gate.py).

Covers the layer_1_read.md edge cases: missing file, undecodable file,
incompatible encodings (D4), empty file (header-only vs literal 0 bytes),
BOM, same file passed twice, plus the run/export/report/gate contract
(architecture.md) and the exact LayerResult.extras shape layers 2/3 depend
on (df_left/df_right, left_encoding/right_encoding, files, summary).
"""

from __future__ import annotations

import json
import os
import types
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from src.layers.layer_1_read import gate, read
from src.utils.execution import ExecutionContext


# ---------------------------------------------------------------------------
# local config helper -- make_config (conftest.py, shared across layers) only
# sets DATA_OUTPUT_ROOT/INPUT_LEFT/INPUT_RIGHT; layer 1 additionally needs
# CSV_DELIMITER/CSV_HEADER_ROW (D13), so this wraps it without touching the
# shared fixture other layers rely on.
# ---------------------------------------------------------------------------


@pytest.fixture
def read_config(make_config):
    def _make(left, right, *, output_root=None, delimiter=",", header_row=0):
        config = make_config(left=left, right=right, output_root=output_root)
        config.CSV_DELIMITER = delimiter
        config.CSV_HEADER_ROW = header_row
        return config

    return _make


def _bare_config(left, right, *, delimiter=",", header_row=0) -> types.SimpleNamespace:
    """A config for tests that only call run() directly (no ExecutionContext)."""
    return types.SimpleNamespace(
        INPUT_LEFT=Path(left),
        INPUT_RIGHT=Path(right),
        CSV_DELIMITER=delimiter,
        CSV_HEADER_ROW=header_row,
    )


# ---------------------------------------------------------------------------
# pure step functions
# ---------------------------------------------------------------------------


def test_check_exists_true(fixtures_dir):
    side = read.check_exists("left", fixtures_dir / "identical_left.csv")
    assert side.exists is True
    assert side.status == "ok"
    assert side.detail is None


def test_check_exists_false(tmp_path):
    side = read.check_exists("right", tmp_path / "does_not_exist.csv")
    assert side.exists is False
    assert side.status == "missing"
    assert "not found" in side.detail


def test_detect_file_encoding_noop_when_missing(tmp_path):
    side = read.check_exists("left", tmp_path / "nope.csv")
    result = read.detect_file_encoding(side)
    assert result is side  # unchanged, no I/O attempted


def test_detect_file_encoding_undecodable(tmp_path):
    path = tmp_path / "binary.csv"
    path.write_bytes(os.urandom(200))
    side = read.check_exists("left", path)
    result = read.detect_file_encoding(side)
    assert result.status == "undecodable"
    assert result.detected is None


def test_detect_file_encoding_success(fixtures_dir):
    side = read.check_exists("left", fixtures_dir / "identical_left.csv")
    result = read.detect_file_encoding(side)
    assert result.status == "ok"
    assert result.encoding_normalized == "utf-8"


def test_normalize_encoding_reads_through_detected(fixtures_dir):
    side = read.check_exists("left", fixtures_dir / "identical_left.csv")
    side = read.detect_file_encoding(side)
    assert read.normalize_encoding(side) == "utf-8"
    assert read.normalize_encoding(read.check_exists("x", Path("nope"))) is None


def test_load_csv_noop_when_not_ok(tmp_path):
    side = read.check_exists("left", tmp_path / "nope.csv")
    result = read.load_csv(side, delimiter=",", header_row=0)
    assert result is side


def test_load_csv_success(fixtures_dir):
    side = read._read_side("left", fixtures_dir / "identical_left.csv", delimiter=",", header_row=0)
    assert side.status == "ok"
    assert side.df is not None
    assert list(side.df.columns) == ["id", "name", "value"]
    assert len(side.df) == 5


def test_load_csv_parse_error(tmp_path):
    path = tmp_path / "ragged.csv"
    path.write_text("id,name,value\r\n1,Alice,100\r\n2,Bob,200,extra,fields\r\n", encoding="utf-8")
    side = read._read_side("left", path, delimiter=",", header_row=0)
    assert side.status == "parse_error"
    assert side.df is None


def test_load_csv_zero_byte_file_is_parse_error(tmp_path):
    """A literal 0-byte file has no header row to parse -- distinct from the
    'header only' success case (spec: 'empty file... readable'); pandas
    raises EmptyDataError here, which load_csv reports as parse_error."""
    path = tmp_path / "zero.csv"
    path.write_bytes(b"")
    side = read._read_side("left", path, delimiter=",", header_row=0)
    assert side.status == "parse_error"
    assert side.df is None


# ---------------------------------------------------------------------------
# run() -- success paths
# ---------------------------------------------------------------------------


def test_run_identical_fixtures_success(fixtures_dir):
    config = _bare_config(fixtures_dir / "identical_left.csv", fixtures_dir / "identical_right.csv")
    result = read.run(config)

    assert result.name == "layer_1_read"
    assert result.verdict == "success"
    assert list(result.data.columns) == [
        "file",
        "path",
        "exists",
        "encoding",
        "encoding_normalized",
        "rows",
        "columns",
        "status",
    ]
    assert len(result.data) == 2
    assert set(result.data["status"]) == {"ok"}

    assert isinstance(result.extras["df_left"], pd.DataFrame)
    assert isinstance(result.extras["df_right"], pd.DataFrame)
    assert result.extras["left_encoding"] == "utf-8"
    assert result.extras["right_encoding"] == "utf-8"
    assert result.extras["files"] == {
        "left": {"path": (fixtures_dir / "identical_left.csv").as_posix(), "encoding": "utf-8"},
        "right": {"path": (fixtures_dir / "identical_right.csv").as_posix(), "encoding": "utf-8"},
    }
    assert result.extras["summary"] == {
        "rows_left": 5,
        "rows_right": 5,
        "columns_left": 3,
        "columns_right": 3,
    }
    assert result.extras["failure_reasons"] == []


def test_run_same_file_passed_twice_succeeds(fixtures_dir):
    """Edge case: same file for left and right -- allowed, later layers find no diffs."""
    path = fixtures_dir / "identical_left.csv"
    config = _bare_config(path, path)
    result = read.run(config)

    assert result.verdict == "success"
    assert result.extras["df_left"].equals(result.extras["df_right"])


def test_run_header_only_file_is_success_with_zero_rows(tmp_path):
    """Edge case: empty file (header only) -- readable, 0 data rows, still success."""
    left = tmp_path / "header_only_left.csv"
    right = tmp_path / "header_only_right.csv"
    left.write_text("id,name,value\n", encoding="utf-8")
    right.write_text("id,name,value\n", encoding="utf-8")

    result = read.run(_bare_config(left, right))

    assert result.verdict == "success"
    assert result.extras["summary"]["rows_left"] == 0
    assert result.extras["summary"]["rows_right"] == 0
    assert result.extras["summary"]["columns_left"] == 3


def test_run_bom_file_normalizes_to_utf8_and_strips_marker(tmp_path):
    """Edge case: BOM -- utf-8-sig normalizes to utf-8 and the BOM doesn't
    leak into the first column name."""
    left = tmp_path / "bom_left.csv"
    left.write_bytes(b"\xef\xbb\xbfid,name,value\r\n1,Alice,100\r\n")
    right = tmp_path / "bom_right.csv"
    right.write_text("id,name,value\n1,Alice,100\n", encoding="utf-8")

    result = read.run(_bare_config(left, right))

    assert result.verdict == "success"
    assert result.extras["left_encoding"] == "utf-8"
    assert list(result.extras["df_left"].columns) == ["id", "name", "value"]
    left_row = result.data[result.data["file"] == "left"].iloc[0]
    assert left_row["encoding_normalized"] == "utf-8"


# ---------------------------------------------------------------------------
# run() -- failure paths
# ---------------------------------------------------------------------------


def test_run_missing_file_failed(fixtures_dir, tmp_path):
    config = _bare_config(fixtures_dir / "identical_left.csv", tmp_path / "does_not_exist.csv")
    result = read.run(config)

    assert result.verdict == "failed"
    right_row = result.data[result.data["file"] == "right"].iloc[0]
    assert right_row["exists"] == False  # noqa: E712
    assert right_row["status"] == "missing"
    left_row = result.data[result.data["file"] == "left"].iloc[0]
    assert left_row["status"] == "ok"

    # Per-side independence: left still loaded even though overall verdict failed.
    assert result.extras["df_left"] is not None
    assert result.extras["df_right"] is None
    assert any("right" in reason for reason in result.extras["failure_reasons"])


def test_run_both_files_missing_failed(tmp_path):
    result = read.run(_bare_config(tmp_path / "a.csv", tmp_path / "b.csv"))
    assert result.verdict == "failed"
    assert set(result.data["status"]) == {"missing"}
    assert result.extras["df_left"] is None
    assert result.extras["df_right"] is None


def test_run_undecodable_file_failed(tmp_path):
    left = tmp_path / "left.csv"
    left.write_text("id,name\n1,Alice\n", encoding="utf-8")
    right = tmp_path / "right.csv"
    right.write_bytes(os.urandom(200))

    result = read.run(_bare_config(left, right))

    assert result.verdict == "failed"
    right_row = result.data[result.data["file"] == "right"].iloc[0]
    assert right_row["status"] == "undecodable"
    assert result.extras["right_encoding"] is None
    assert result.extras["df_left"] is not None
    assert result.extras["df_right"] is None


def test_run_incompatible_encodings_failed(tmp_path):
    """D4: a genuine mismatch needs the *normalized* encodings to differ.

    utf-8 (with accented chars) vs cp1252 (with different accented chars)
    is a real conflict -- unlike the shared encoding_conflict_* fixture
    pair, see test_run_encoding_conflict_fixture_actually_succeeds below.
    """
    left = tmp_path / "utf8.csv"
    left.write_text("id,name,value\r\n1,Alíce,100\r\n2,Böb,200\r\n", encoding="utf-8")
    right = tmp_path / "cp1252.csv"
    right.write_text(
        "id,name,value\r\n1,Résumé,100\r\n2,Café,200\r\n3,Naïve,300\r\n4,Piñata,400\r\n",
        encoding="cp1252",
    )

    result = read.run(_bare_config(left, right))

    assert result.verdict == "failed"
    assert set(result.data["status"]) == {"encoding_mismatch"}
    assert result.extras["left_encoding"] != result.extras["right_encoding"]
    # Both sides were individually decodable/loadable -- per-side dataframes
    # still populated even though the pair as a whole is incompatible.
    assert result.extras["df_left"] is not None
    assert result.extras["df_right"] is not None
    assert len(result.extras["failure_reasons"]) == 2


def test_run_parse_error_failed(fixtures_dir, tmp_path):
    left = tmp_path / "ragged.csv"
    left.write_text("id,name,value\r\n1,Alice,100\r\n2,Bob,200,extra,fields\r\n", encoding="utf-8")

    result = read.run(_bare_config(left, fixtures_dir / "identical_right.csv"))

    assert result.verdict == "failed"
    left_row = result.data[result.data["file"] == "left"].iloc[0]
    assert left_row["status"] == "parse_error"
    assert result.extras["df_left"] is None
    assert result.extras["df_right"] is not None


def test_run_encoding_conflict_fixture_actually_succeeds(fixtures_dir):
    """Documents a mismatch between tests/fixtures/README.md's description of
    the encoding_conflict_* pair ("hard-failure if encodings are
    incompatible") and its actual bytes.

    encoding_conflict_left.csv is UTF-8 with real accented characters
    (detected encoding "utf-8"). encoding_conflict_right.csv's *content* is
    plain ASCII -- no non-ASCII byte appears anywhere in it (confirmed by
    reading the raw bytes), so charset-normalizer correctly reports it as
    "ascii", not "iso-8859-1"; there is no byte sequence in the file to
    distinguish those encodings. Per D4, ascii normalizes to utf-8, so the
    two sides' *normalized* encodings match and layer 1 (correctly,
    per D4's own stated purpose: "a pure-ASCII file must not fail against a
    UTF-8 file") reports success, not failure.

    tests/test_encoding.py already anticipates exactly this in
    test_detect_encoding_ascii_fixture_of_conflict_pair's docstring. This
    test pins the resulting layer 1 behavior; see also
    test_run_incompatible_encodings_failed above for a synthetic pair that
    *does* genuinely conflict (utf-8 vs cp1252 with real high-byte content
    on both sides), which exercises the actual hard-failure path.
    """
    result = read.run(
        _bare_config(fixtures_dir / "encoding_conflict_left.csv", fixtures_dir / "encoding_conflict_right.csv")
    )
    assert result.extras["left_encoding"] == "utf-8"
    assert result.extras["right_encoding"] == "utf-8"
    assert result.verdict == "success"


# ---------------------------------------------------------------------------
# export / report (real I/O via ExecutionContext, per architecture.md:
# artifacts are always written before the gate runs, including on failure)
# ---------------------------------------------------------------------------


def test_export_writes_csv_and_txt_success(read_config, fixtures_dir):
    config = read_config(fixtures_dir / "identical_left.csv", fixtures_dir / "identical_right.csv")
    ctx = ExecutionContext.create(config, now=datetime(2026, 7, 18, 12, 0, 0))
    result = read.run(config)

    read.export(result, ctx)

    csv_path = ctx.csv_path(result.name)
    txt_path = ctx.txt_path(result.name)
    assert csv_path.is_file()
    assert txt_path.is_file()

    csv_df = pd.read_csv(csv_path)
    assert list(csv_df["file"]) == ["left", "right"]
    assert list(csv_df["status"]) == ["ok", "ok"]

    txt_text = txt_path.read_text(encoding="utf-8")
    assert "Verdict:    success" in txt_text
    assert "identical_left.csv" in txt_text
    assert "identical_right.csv" in txt_text


def test_export_writes_artifacts_even_on_failure(read_config, fixtures_dir, tmp_path):
    config = read_config(fixtures_dir / "identical_left.csv", tmp_path / "missing.csv")
    ctx = ExecutionContext.create(config)
    result = read.run(config)
    assert result.verdict == "failed"

    read.export(result, ctx)

    assert ctx.csv_path(result.name).is_file()
    assert ctx.txt_path(result.name).is_file()
    assert "Verdict:    failed" in ctx.txt_path(result.name).read_text(encoding="utf-8")


def test_report_writes_pdf_success(read_config, fixtures_dir):
    config = read_config(fixtures_dir / "identical_left.csv", fixtures_dir / "identical_right.csv")
    ctx = ExecutionContext.create(config, now=datetime(2026, 7, 18, 12, 0, 0))
    result = read.run(config)

    read.report(result, ctx)

    pdf_path = ctx.pdf_path(result.name)
    assert pdf_path.is_file()
    assert pdf_path.stat().st_size > 0


def test_report_writes_pdf_on_failure_with_reason(read_config, fixtures_dir, tmp_path):
    config = read_config(fixtures_dir / "identical_left.csv", tmp_path / "missing.csv")
    ctx = ExecutionContext.create(config)
    result = read.run(config)

    read.report(result, ctx)

    pdf_path = ctx.pdf_path(result.name)
    assert pdf_path.is_file()
    assert pdf_path.stat().st_size > 0


def test_export_and_report_run_before_gate_on_failure(read_config, fixtures_dir, tmp_path):
    """Architecture.md: artifacts are always written before the gate runs,
    including on failure -- simulate the orchestrator's actual call order."""
    config = read_config(fixtures_dir / "identical_left.csv", tmp_path / "missing.csv")
    ctx = ExecutionContext.create(config)
    result = read.run(config)

    read.export(result, ctx)
    read.report(result, ctx)
    decision = gate.decide(result.verdict)

    assert ctx.csv_path(result.name).is_file()
    assert ctx.txt_path(result.name).is_file()
    assert ctx.pdf_path(result.name).is_file()
    assert decision == "STOP"


def test_manifest_integration_uses_layer1_files_extra(read_config, fixtures_dir):
    """extras["files"] must be exactly the shape execution.py's manifest_dict()
    reads verbatim into the manifest's top-level "files" key."""
    config = read_config(fixtures_dir / "identical_left.csv", fixtures_dir / "identical_right.csv")
    ctx = ExecutionContext.create(config, now=datetime(2026, 7, 18, 12, 0, 0))
    result = read.run(config)
    ctx.record(result)

    manifest_path = ctx.write_manifest()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["files"] == result.extras["files"]
    assert manifest["layers"]["layer_1_read"]["summary"] == result.extras["summary"]
    assert manifest["exit_code"] == 0


# ---------------------------------------------------------------------------
# gate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "verdict,expected",
    [
        ("success", "CONTINUE"),
        ("failed", "STOP"),
    ],
)
def test_gate_decide(verdict, expected):
    assert gate.decide(verdict) == expected
