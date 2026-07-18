# Shared utilities spec (`src/utils/`)

The spec's tree shows a single `utils.py`; keep that as the public facade but
implement as focused modules re-exported from it if it grows past ~300 lines.

## Modules

### execution.py — `ExecutionContext`
- Creates `data/execution=<YYYY-MM-DD_HH-MM-SS>/` (+ `_1` suffix on collision, D10)
  and the four layer subfolders.
- Holds config, per-layer `LayerResult`s and verdicts, input-file content hash.
- `write_manifest()` → `manifest.json` (see dashboard.md schema) and rebuilds
  the root `data/executions.json` index by listing `execution=*` folders.

### artifacts.py — CSV/TXT writers
- `write_csv(df, path)` — UTF-8, no index.
- `write_txt(df, path, header_lines)` — fixed-width table (D12) with the
  standard header block (files, encodings, verdict, timestamp).
- Layer code never calls `to_csv` directly — one place controls format.

### pdf.py — report engine (fpdf2 + matplotlib)
- `ReportBuilder`: standard page header (title, file names, encodings,
  timestamp), verdict banner (green success / amber completed-with-differences
  / red failed), `add_table(df)`, `add_chart(fig)`.
- Charts are matplotlib figures rendered to PNG in-memory and embedded.
  `barh_chart(labels, values, grey_mask)` covers layers 3 and 4 (D14).
- Load the `dataviz` skill before styling charts when implementing.

### encoding.py
- `detect_encoding(path) -> DetectedEncoding` via charset-normalizer.
- `normalize(enc)` — ascii→utf-8, utf-8-sig→utf-8 (D4).

### keys.py
- Composite-key helpers: `key_frame(df, key_columns)`, duplicate detection —
  shared by layers 3 and 4 so pairing logic can't drift apart.

## Testing
Every util is pure or thin-I/O; test with 5–20 row fixtures under
`tests/fixtures/`. PDF tests assert the file is created and non-empty +
builder calls succeed (no pixel testing).
