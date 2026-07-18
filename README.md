# compare-dataframes

Compare two CSV files layer-by-layer with gated reports and a browser dashboard.

The pipeline runs four layers in order — **read → compare columns → compare
rows → compare values** — each producing CSV / TXT / PDF artifacts and a
verdict. A per-layer gate can stop the run early (e.g. unreadable files, no
common columns). Results are indexed in `data/` for the dashboard.

Project knowledge lives in `.claude/` (see [CLAUDE.md](CLAUDE.md) for the map):
requirements, decisions, architecture, per-layer specs, and the dashboard
design.

## Requirements

- Python ≥ 3.12
- [`uv`](https://docs.astral.sh/uv/) for dependency management

```bash
uv sync
```

## Configure

Edit [src/config/config.py](src/config/config.py):

- `INPUT_LEFT` / `INPUT_RIGHT` — the two CSVs to compare
- `KEY_COLUMNS` — the composite row key (default `["id"]`)
- `CSV_DELIMITER` / `CSV_HEADER_ROW` — CSV parsing options
- `PER_COLUMN_NUMERIC_TOLERANCE` — optional per-column numeric tolerance
- `ACCEPTED_DIFFERENCES_PATH` — value differences to tolerate
  ([docs/layer_4_compare_values/accepted_differences.csv](docs/layer_4_compare_values/accepted_differences.csv))

## Run the pipeline

```bash
uv run python -m src.main
```

This writes a timestamped execution folder under `data/` (artifacts per layer,
`manifest.json`) and rebuilds `data/executions.json`. The process exit code
summarizes the outcome:

| Exit | Meaning                                                                    |
|------|----------------------------------------------------------------------------|
| `0`  | All layers passed (accepted-only value diffs still count as passed)        |
| `1`  | Layer 1 — read failure (missing/undecodable/incompatible files)            |
| `2`  | Layer 2 — no common columns / missing key column                           |
| `3`  | Layer 3 — row differences or duplicate keys                                |
| `4`  | Layer 4 — non-accepted value differences                                   |
| `5`  | Unexpected crash (a `manifest.json` with `crashed: true` is still written) |

## View the dashboard

The dashboard reads `data/` over HTTP — opening it via `file://` is
unsupported. Serve from the **repo root**:

```bash
uv run python -m http.server 8000
```

Then open <http://localhost:8000/src/main.html>.

The dashboard lists every execution (newest first), shows each layer's verdict,
summary, charts, and full detail table with Excel-like sorting/filtering.
Accepted value differences are badged; click one for its recorded reason.

## Tests

```bash
uv run pytest
```
