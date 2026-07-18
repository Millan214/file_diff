"""Shared pytest fixtures for the compare-dataframes test suite."""

from __future__ import annotations

import types
from pathlib import Path

import pytest


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def make_config(tmp_path):
    """Build a minimal config-like namespace for ExecutionContext tests.

    Mirrors the surface of ``src/config/config.py`` that ``ExecutionContext``
    actually reads (``DATA_OUTPUT_ROOT``, ``INPUT_LEFT``, ``INPUT_RIGHT``)
    without touching the real project ``data/`` directory.
    """

    def _make(
        left: Path | str = "tests/fixtures/identical_left.csv",
        right: Path | str = "tests/fixtures/identical_right.csv",
        output_root: Path | None = None,
    ) -> types.SimpleNamespace:
        return types.SimpleNamespace(
            DATA_OUTPUT_ROOT=output_root if output_root is not None else tmp_path,
            INPUT_LEFT=Path(left),
            INPUT_RIGHT=Path(right),
        )

    return _make
