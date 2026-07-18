# Layer 1 — read

## Purpose
Load both input files, detect encodings, hard-gate the pipeline.

## run
1. Check both paths exist. Missing file → `failed` (report still lists both files with status per file).
2. Detect encoding per file with `charset-normalizer`; normalize ASCII → UTF-8 (D4).
3. If normalized encodings differ, or a file fails to decode → `failed`.
4. Read both CSVs with pandas using the detected encoding + config delimiter (D13). Parse error → `failed`.
5. Success → `LayerResult` with `df_left`, `df_right`, encodings, row/col counts.

Pure-function decomposition: `check_exists`, `detect_encoding`,
`normalize_encoding`, `load_csv` — composed by `read.py`; no I/O outside
`load_csv`'s reads.

## Exports (CSV/TXT)
One row per file: `file, path, exists, encoding, encoding_normalized, rows, columns, status`.

## PDF report
Standard header + the table above + verdict banner
(success / failed, with the failing reason spelled out).

## Gate
`failed → STOP` (exit code 1). Otherwise CONTINUE.

## Edge cases
- Empty file (0 bytes / header only): readable, but 0 data rows — success here; later layers surface the consequences.
- BOM: `utf-8-sig` normalizes to UTF-8.
- Same file passed twice: allowed; comparison will simply find no differences.
