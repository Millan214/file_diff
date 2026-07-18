"""Layer 1 -- read files, detect encodings, and hard-gate the pipeline.

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

Nothing here does exports/reports I/O except ``export``/``report`` below,
which are the only functions in this module allowed to touch
``src/utils/artifacts.py`` / ``src/utils/pdf.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pandas as pd

from src.utils.artifacts import write_csv, write_txt
from src.utils.encoding import DetectedEncoding, EncodingDetectionError, detect_encoding
from src.utils.execution import ExecutionContext, LayerResult, Verdict
from src.utils.pdf import ReportBuilder

NAME = "layer_1_read"

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


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


def run(config: Any) -> LayerResult:
    """Load both configured input files and hard-gate on any failure (layer 1 spec)."""
    left = _read_side(
        "left", config.INPUT_LEFT, delimiter=config.CSV_DELIMITER, header_row=config.CSV_HEADER_ROW
    )
    right = _read_side(
        "right", config.INPUT_RIGHT, delimiter=config.CSV_DELIMITER, header_row=config.CSV_HEADER_ROW
    )
    left, right = _mark_encoding_mismatch(left, right)

    both_loaded = (
        left.status == "ok" and right.status == "ok" and left.df is not None and right.df is not None
    )
    verdict: Verdict = "success" if both_loaded else "failed"

    data = pd.DataFrame([_side_row(left), _side_row(right)], columns=_EXPORT_COLUMNS)

    extras: dict[str, Any] = {
        "df_left": left.df,
        "df_right": right.df,
        "left_encoding": left.encoding_normalized,
        "right_encoding": right.encoding_normalized,
        "files": {
            "left": {"path": left.path.as_posix(), "encoding": left.encoding_normalized},
            "right": {"path": right.path.as_posix(), "encoding": right.encoding_normalized},
        },
        "summary": {
            "rows_left": len(left.df) if left.df is not None else None,
            "rows_right": len(right.df) if right.df is not None else None,
            "columns_left": len(left.df.columns) if left.df is not None else None,
            "columns_right": len(right.df.columns) if right.df is not None else None,
        },
        "failure_reasons": _failure_reasons(left, right) if verdict == "failed" else [],
    }

    return LayerResult(name=NAME, verdict=verdict, data=data, extras=extras)


# ---------------------------------------------------------------------------
# export / report (the only I/O besides load_csv/detect_encoding above --
# always called before the gate runs, including on a "failed" verdict)
# ---------------------------------------------------------------------------


def _header_lines(result: LayerResult, ctx: ExecutionContext) -> list[str]:
    left_enc = result.extras.get("left_encoding") or "unknown"
    right_enc = result.extras.get("right_encoding") or "unknown"
    files = result.extras.get("files", {})
    left_path = files.get("left", {}).get("path", str(ctx.config.INPUT_LEFT))
    right_path = files.get("right", {}).get("path", str(ctx.config.INPUT_RIGHT))
    return [
        f"Left file:  {left_path}   (encoding: {left_enc})",
        f"Right file: {right_path}   (encoding: {right_enc})",
        f"Verdict:    {result.verdict}",
        f"Generated:  {ctx.created_at.strftime('%Y-%m-%d %H:%M:%S')}",
    ]


def export(result: LayerResult, ctx: ExecutionContext) -> None:
    """Write the layer 1 CSV + TXT exports (D12). Never calls ``.to_csv`` directly."""
    write_csv(result.data, ctx.csv_path(result.name))
    write_txt(result.data, ctx.txt_path(result.name), header_lines=_header_lines(result, ctx))


def report(result: LayerResult, ctx: ExecutionContext) -> None:
    """Write the layer 1 PDF report: standard header + table + verdict banner."""
    files = result.extras.get("files", {})
    left_path = files.get("left", {}).get("path", str(ctx.config.INPUT_LEFT))
    right_path = files.get("right", {}).get("path", str(ctx.config.INPUT_RIGHT))

    builder = ReportBuilder(
        title="Layer 1 -- Read",
        left_file=left_path,
        right_file=right_path,
        left_encoding=result.extras.get("left_encoding") or "unknown",
        right_encoding=result.extras.get("right_encoding") or "unknown",
        verdict=result.verdict,
        timestamp=ctx.created_at,
    )
    builder.add_table(result.data, heading="Files")

    if result.verdict == "failed":
        reasons = result.extras.get("failure_reasons") or []
        reason_text = " | ".join(reasons) if reasons else "See status column above."
        builder.add_paragraph(f"Failing reason(s): {reason_text}")

    builder.output(str(ctx.pdf_path(result.name)))
