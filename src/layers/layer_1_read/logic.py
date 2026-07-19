"""Layer 1 pure logic -- read files, detect encodings, decide the verdict.

Purpose (``.claude/layers/layer_1_read.md``): load both input files, detect
their encodings, and hard-fail the pipeline (D4, D13) if either file is
missing, undecodable, mutually incompatible in (normalized) encoding, or
fails to parse as CSV. Verdict is only ever ``"success"`` or ``"failed"``.

Pure-function decomposition per the layer spec -- ``check_exists``,
``detect_file_encoding`` (delegates to ``src/utils/encoding.py``),
``normalize_encoding``, ``load_csv`` -- chained per file (left/right) in
``_read_side``. ``load_csv`` is the only place this module reads file
*content*; ``check_exists``/``detect_file_encoding`` each do a single,
already-isolated filesystem touch (``pathlib.Path.is_file`` /
``src/utils/encoding.py``'s own I/O) rather than reimplementing anything.
Export/report I/O lives in ``output.py``; ``run`` in ``run.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pandas as pd

from src.utils.encoding import DetectedEncoding, EncodingDetectionError, detect_encoding

LAYER_NAME = "layer_1_read"

#: Exceptions load_csv treats as "this file failed to parse as CSV" (spec
#: step 4). EmptyDataError covers a literal 0-byte file (no header row to
#: parse) -- distinct from a *header-only* file (0 data rows), which reads
#: fine and is the "empty file" success case the layer spec describes.
_PARSE_ERRORS = (
    pd.errors.ParserError,
    pd.errors.EmptyDataError,
    UnicodeDecodeError,
    LookupError,
    OSError,
)

#: Column order for the export table (layer spec's Exports section).
_EXPORT_COLUMNS = [
    "file",
    "path",
    "exists",
    "encoding",
    "encoding_normalized",
    "rows",
    "columns",
    "status",
]


@dataclass(frozen=True)
class SideResult:
    """Everything learned about one side (left/right) after its own pipeline runs.

    ``status`` starts at ``"missing"`` and is only ever tightened by a later
    step (never reset back to "ok" once something has gone wrong), so it
    always reflects the first failure encountered for this side.
    """

    file: str
    path: Path
    exists: bool = False
    detected: DetectedEncoding | None = None
    df: pd.DataFrame | None = None
    status: str = "missing"
    detail: str | None = None

    @property
    def encoding(self) -> str | None:
        return self.detected.encoding if self.detected is not None else None

    @property
    def encoding_normalized(self) -> str | None:
        return self.detected.normalized if self.detected is not None else None


# ---------------------------------------------------------------------------
# Pure per-file steps (spec: check_exists, detect_encoding, normalize_encoding,
# load_csv)
# ---------------------------------------------------------------------------


def check_exists(file: str, path: Path) -> SideResult:
    """Step 1: does the path exist as a file?"""
    path = Path(path)
    exists = path.is_file()
    return SideResult(
        file=file,
        path=path,
        exists=exists,
        status="ok" if exists else "missing",
        detail=None if exists else f"file not found: {path.as_posix()}",
    )


def detect_file_encoding(side: SideResult) -> SideResult:
    """Step 2: detect this side's encoding via charset-normalizer (D4).

    No-op if an earlier step (``check_exists``) already failed.
    """
    if side.status != "ok":
        return side
    try:
        detected = detect_encoding(side.path)
    except EncodingDetectionError as exc:
        return replace(side, status="undecodable", detail=str(exc))
    return replace(side, detected=detected)


def normalize_encoding(side: SideResult) -> str | None:
    """The normalized encoding name (D4) used for the cross-file compatibility check.

    A thin accessor over ``DetectedEncoding.normalized`` -- kept as its own
    function so the four spec steps line up 1:1 with named functions.
    """
    return side.encoding_normalized


def load_csv(side: SideResult, *, delimiter: str, header_row: int) -> SideResult:
    """Step 4: read this side's CSV with pandas. The only file-content read here.

    No-op if an earlier step already failed (missing/undecodable).
    """
    if side.status != "ok" or side.detected is None:
        return side
    try:
        df = pd.read_csv(
            side.path,
            sep=delimiter,
            header=header_row,
            encoding=side.detected.normalized,
        )
    except _PARSE_ERRORS as exc:
        return replace(side, status="parse_error", detail=f"failed to parse CSV: {exc}")
    return replace(side, df=df)


def _read_side(file: str, path: Path, *, delimiter: str, header_row: int) -> SideResult:
    """check_exists -> detect_file_encoding -> load_csv, pipe-style, for one side."""
    side = check_exists(file, path)
    side = detect_file_encoding(side)
    side = load_csv(side, delimiter=delimiter, header_row=header_row)
    return side


def _mark_encoding_mismatch(left: SideResult, right: SideResult) -> tuple[SideResult, SideResult]:
    """Step 3: hard-fail both sides if they exist+decode but disagree after normalization.

    Runs *after* ``load_csv`` in ``_read_side`` (each side is independently
    loadable), but a normalized-encoding mismatch still flips the overall
    verdict to failed per D4/the layer spec -- the loaded dataframes stay
    available in ``extras`` (useful for the report/export), the mismatch is
    only reflected in ``status``/verdict.
    """
    if (
        left.status == "ok"
        and right.status == "ok"
        and left.encoding_normalized is not None
        and right.encoding_normalized is not None
        and left.encoding_normalized != right.encoding_normalized
    ):
        reason = (
            f"incompatible encodings: left={left.encoding_normalized} "
            f"right={right.encoding_normalized}"
        )
        left = replace(left, status="encoding_mismatch", detail=reason)
        right = replace(right, status="encoding_mismatch", detail=reason)
    return left, right


def _side_row(side: SideResult) -> dict[str, Any]:
    return {
        "file": side.file,
        "path": side.path.as_posix(),
        "exists": side.exists,
        "encoding": side.encoding,
        "encoding_normalized": side.encoding_normalized,
        "rows": len(side.df) if side.df is not None else None,
        "columns": len(side.df.columns) if side.df is not None else None,
        "status": side.status,
    }


def _failure_reasons(left: SideResult, right: SideResult) -> list[str]:
    return [f"{side.file}: {side.detail}" for side in (left, right) if side.status != "ok"]
