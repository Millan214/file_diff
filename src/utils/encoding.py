"""Encoding detection and normalization (D4).

Detection uses ``charset-normalizer``. Normalization treats ASCII as a
subset of UTF-8 and folds the UTF-8 BOM variant into plain UTF-8, so a
pure-ASCII file never conflicts with a UTF-8 file, and a UTF-8 file with a
BOM never conflicts with one without. Everything else (e.g. cp1252,
iso-8859-1) is left as detected — a genuine mismatch there is a hard
failure for layer 1 to report.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from charset_normalizer import from_path

#: Encoding names (lowercase, dash form) folded into "utf-8" by normalize().
_UTF8_ALIASES = {"ascii", "us-ascii", "utf-8-sig"}


class EncodingDetectionError(ValueError):
    """Raised when a file cannot be read or its encoding cannot be detected."""


def normalize(encoding: str) -> str:
    """Normalize an encoding name per D4.

    ``ascii`` -> ``utf-8`` (ASCII is a subset of UTF-8) and ``utf-8-sig`` ->
    ``utf-8`` (BOM presence doesn't change the decoded content). Any other
    name is lowercased and dash-normalized but otherwise left alone.
    """
    name = encoding.strip().lower().replace("_", "-")
    if name in _UTF8_ALIASES:
        return "utf-8"
    return name


@dataclass(frozen=True)
class DetectedEncoding:
    """Result of :func:`detect_encoding`.

    ``encoding`` is the raw name charset-normalizer reported (dash-normalized,
    e.g. ``"utf-8"``, ``"ascii"``, ``"cp1252"``); ``normalized`` is that name
    after D4 folding — compare ``normalized`` across files to decide
    compatibility.
    """

    path: Path
    encoding: str
    normalized: str
    bom: bool = False


def detect_encoding(path: Path) -> DetectedEncoding:
    """Detect a file's encoding via charset-normalizer.

    Raises :class:`EncodingDetectionError` if the file cannot be opened/read
    or if no encoding could be determined at all (charset-normalizer found
    no viable candidate).
    """
    path = Path(path)
    try:
        result = from_path(path)
    except OSError as exc:
        raise EncodingDetectionError(f"Could not read {path}: {exc}") from exc

    best = result.best()
    if best is None:
        raise EncodingDetectionError(f"Could not detect an encoding for {path}")

    raw = best.encoding.replace("_", "-")
    return DetectedEncoding(
        path=path,
        encoding=raw,
        normalized=normalize(raw),
        bom=bool(best.byte_order_mark),
    )
