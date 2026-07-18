"""CSV and fixed-width TXT writers.

Per the utils README, these are the ONLY place ``to_csv``/table formatting
happens — layer modules must never call ``to_csv`` directly, so CSV/TXT
output can never drift apart in format.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pandas as pd


def write_csv(df: pd.DataFrame, path: Path) -> Path:
    """Write ``df`` to ``path`` as UTF-8 CSV, no index column.

    Creates parent directories as needed (layer export code should not have
    to pre-create ``execution=<ts>/layer_N_<name>/`` itself).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8")
    return path


def write_txt(
    df: pd.DataFrame,
    path: Path,
    header_lines: Sequence[str] | None = None,
) -> Path:
    """Write ``df`` to ``path`` as a fixed-width text table (D12).

    ``header_lines`` is the standard header block (files, encodings,
    verdict, timestamp) that callers build; it is written verbatim, one
    line each, followed by a blank line and then the same table as the CSV
    rendered fixed-width via ``DataFrame.to_string`` — "New column"
    requirements apply to the TXT exactly as to the CSV (D12).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = list(header_lines or [])
    if lines:
        lines.append("")

    lines.append(df.to_string(index=False))

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
