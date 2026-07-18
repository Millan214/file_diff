# Distilled requirements

Source of truth: `req.txt` (verbatim user spec). This file restates it with the
ambiguities resolved per `.claude/docs/decisions.md`.

## What the tool does

A Python CLI that compares two CSV files through a 4-layer gated pipeline. Each
layer writes three artifacts (CSV, TXT, PDF) into a timestamped execution
folder, then a gate decides whether the pipeline continues. A static HTML
dashboard (`main.html`) browses all executions.

## Pipeline

| # | Layer | Compares | Gate behavior (resolved) |
|---|---|---|---|
| 1 | `read` | files exist + encodings | **Hard stop** if a file is missing, unreadable, or encodings differ meaningfully (D4) |
| 2 | `compare_columns` | column names + dtypes | **Soft**: continue with common columns. Hard stop only if the common set is empty or missing a key column (D5) |
| 3 | `compare_rows` | row presence by key + duplicates | **Soft**: continue to layer 4 with inner rows; duplicated-key rows excluded (D1) |
| 4 | `compare_values` | cell values on inner rows × common columns | Fails only on differences in non-accepted columns (D3) |

## Artifacts per layer

Every layer writes into `data/execution=<timestamp>/layer_N_<name>/`:

- `layer_N_<name>.csv` — machine-readable result data.
- `layer_N_<name>.txt` — the same data as a human-readable fixed-width table.
- `layer_N_<name>.pdf` — report: file names, encodings, verdict banner
  (success / completed-with-differences / failed), layer-specific tables and
  charts:
  - Layer 2 PDF: columns per file, left-only / right-only / common columns, dtype comparison, the common set the pipeline continues with.
  - Layer 3 PDF: horizontal bar chart — left-only, inner, right-only row counts, and duplicate count.
  - Layer 4 PDF: bar chart of per-column difference counts; accepted-difference columns drawn as grey bars.

Additionally the run writes `manifest.json` at the execution root (for the
dashboard) — see `.claude/docs/dashboard.md`.

## Accepted differences (layer 4)

`docs/layer_4_compare_values/accepted_differences.csv` (repo root `/docs`) with
columns `column, reason, example_left, example_right`. Effects:

- PDF: grey bars for accepted columns.
- CSV/TXT export: extra boolean column `acceptable_difference`.
- HTML: `acceptable_difference` column + grey bars; clicking a grey bar pops up the reason from the docs CSV.
- Verdict: run succeeds if all differences are in accepted columns (D3).

## Dashboard (`src/main.html`)

Static single file served with a local HTTP server. Sidebar with the 4 layers,
header with execution id/date + refresh + execution dropdown, main content
renders each layer's CSV as an Excel-like filterable table mirroring the PDF
content. Details: `.claude/docs/dashboard.md`.

## File structure (target)

```
/root
  pyproject.toml            # uv-managed
  /docs
    /layer_4_compare_values/accepted_differences.csv
  /data
    /input/file1.csv, file2.csv
    /execution=<YYYY-MM-DD_HH-MM-SS>/
      manifest.json
      /layer_1_read/            layer_1_read.{csv,txt,pdf}
      /layer_2_compare_columns/ layer_2_compare_columns.{csv,txt,pdf}
      /layer_3_compare_rows/    layer_3_compare_rows.{csv,txt,pdf}
      /layer_4_compare_values/  layer_4_compare_values.{csv,txt,pdf}
  /src
    main.py                 # orchestrator + CLI
    main.html               # dashboard
    /layers
      /layer_1_read/{read.py, gate.py}
      /layer_2_compare_columns/{compare_columns.py, gate.py}
      /layer_3_compare_rows/{compare_rows.py, gate.py}
      /layer_4_compare_values/{compare_values.py, gate.py}
    /config/config.py
    /utils/utils.py         # may split into modules, see .claude/utils/README.md
  /tests
    /fixtures               # 5–20 row CSV fixtures
```

## Tech stack

Python 3.12+, uv, pandas, charset-normalizer (encoding detection),
fpdf2 + matplotlib (PDF reports & charts), pytest. No web framework — the
dashboard is vanilla HTML/JS served by `python -m http.server`.
