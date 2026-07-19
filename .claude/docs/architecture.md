# Architecture

## Pipeline shape

```
main.py
  └─ ExecutionContext (creates data/executions/execution=<ts>/, holds config, paths, verdicts)
      ├─ Layer 1 read            → run → export(csv,txt) → report(pdf) → gate
      ├─ Layer 2 compare_columns → run → export → report → gate   (passes common columns forward)
      ├─ Layer 3 compare_rows    → run → export → report → gate   (passes inner-row keys forward)
      ├─ Layer 4 compare_values  → run → export → report → gate
      └─ manifest.json + executions.json index → exit code (D11)
```

## The layer contract

Every layer implements the same three phases, in this order — **artifacts are
always written before the pipeline decides whether to continue**, including on
failure:

1. **run** — pure computation. Takes the `LayerResult`s of previous layers +
   config, returns a `LayerResult` dataclass:
   `{name, verdict, data: DataFrame, extras: dict}`.
   Verdicts: `success` | `completed-with-differences` | `failed`.
2. **export** — write `layer_N_<name>.csv` and `.txt` from `result.data`
   (shared writers in utils, D12).
3. **report** — write `layer_N_<name>.pdf`: standard header (file names,
   encodings, timestamp, verdict banner) + layer-specific tables/charts.

After a layer is recorded, the orchestrator (`main.py`) stops the pipeline on
a `failed` verdict and continues on any other. This is a single rule for all
layers — each layer just chooses when to emit `failed`: layer 1 on any read
failure; layer 2 when the common set is empty or missing keys (D5); layer 3
never (row differences stay `completed-with-differences`, D1); layer 4 is
terminal, so its verdict only drives the exit code.

DataFrames pass between layers **in memory** via `ExecutionContext` — the
CSV/TXT/PDF artifacts are outputs for humans and the dashboard, never re-read
by the pipeline.

## Layer inputs/outputs

| Layer | Consumes | Produces for next layer |
|---|---|---|
| 1 | input file paths | `df_left`, `df_right`, encodings |
| 2 | dfs | `common_columns` (order = left file's order), dtype table |
| 3 | dfs + common_columns + KEY_COLUMNS | `inner_keys`, duplicate keys, merge stats |
| 4 | dfs filtered to inner_keys × common_columns | value-diff table |

## Code style {#code-style}

- **Pure functions + `df.pipe`**: each transformation is a small function
  `DataFrame -> DataFrame` (or `-> LayerResult` at the end of a chain), no
  side effects, no I/O. Layer modules read as one pipe chain.
- **Standard layer package**: each layer is a package split into `logic.py`
  (pure computation), `run.py` (`run()` assembles the `LayerResult`), and
  `output.py` (`export()`/`report()` I/O), aggregated by `__init__.py` which
  re-exports the public surface. Layer 4 adds `equality.py` (the D9 matrix) and
  `accepted.py` (the policy loader).
- **Isolation**: business logic (`logic.py`, and layer 4's `equality.py`) never
  touches the filesystem; plumbing (export/report/paths) lives in `output.py`
  and `src/utils/` and is called by the orchestrator. This keeps every
  transformation testable with 5–20 row fixtures.
- The continue/stop decision is a single inlined rule in `main.py`
  (`verdict != "failed"`), not a per-layer module — no I/O, verdict in.

## Error handling

- Expected comparison failures are **verdicts**, not exceptions.
- Unexpected exceptions (bug, disk full) escape to `main.py`, which still
  attempts to write `manifest.json` with `verdict: crashed` and exits ≠ 0.

## Config (`src/config/config.py`)

`KEY_COLUMNS: list[str]` (D2), input paths, delimiter/header options (D13),
per-column numeric tolerances (D9), path to `accepted_differences.csv`.
Plain constants module — no framework.
