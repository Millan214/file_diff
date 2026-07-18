# Dashboard — `src/main.html`

Static, dependency-free HTML/JS/CSS in one file, served from the **repo root**
(so it can fetch `data/...`) via `python -m http.server` — provide
`uv run python -m http.server 8000` in the README and a `serve` script.
Opening via `file://` is unsupported (D6).

## Data contract

The dashboard never parses PDFs — it reads:

- `data/executions.json` — index rebuilt on every run:
  `[{ "id": "execution=2026-07-18_12-00-00", "date": "...", "exit_code": 0 }]`
  (newest first).
- `data/<id>/manifest.json`:
  ```json
  {
    "execution_id": "execution=2026-07-18_12-00-00",
    "created": "2026-07-18T12:00:00",
    "input_hash": "a1b2c3d4",
    "files": {"left": {"path": "...", "encoding": "utf-8"}, "right": {...}},
    "exit_code": 0,
    "layers": {
      "layer_1_read": {"verdict": "success", "csv": "layer_1_read/layer_1_read.csv",
                        "summary": {"rows_left": 100, "rows_right": 101}},
      "layer_3_compare_rows": {"verdict": "completed-with-differences",
                                "summary": {"left_only": 2, "inner": 98, "right_only": 3, "duplicates": 1}},
      "layer_4_compare_values": {"summary": {"diff_counts": {"col": 5}, "accepted_columns": ["col2"]}}
    }
  }
  ```
  `summary` carries the chart numbers so charts don't require CSV parsing.
- Each layer's CSV, fetched relative to the manifest, parsed with a small
  hand-rolled CSV parser (handle quoted fields; no CDN libraries).
- `docs/layer_4_compare_values/accepted_differences.csv` for the reasons popup.

## Layout

- **Sidebar**: the 4 layers, each with a verdict dot (green/amber/red/grey =
  not-run). Click selects the layer view.
- **Header**: execution id + date, dropdown listing executions
  (from `executions.json`), refresh button (re-fetches index + manifest).
- **Main content** per layer mirrors the PDF: verdict banner, summary,
  bar charts (layers 3–4, inline SVG or styled divs), and the CSV as a table.

## Tables — "filterable like Excel"

Per column: header click sorts (asc/desc/none); a filter icon opens a popup
with a search box + distinct-value checkboxes (cap the list at ~1000 distinct
values with a note); active filters combine across columns (AND). Text filter
row under headers is acceptable as the search box. Virtualize or paginate past
~5000 rows.

## Layer-4 specifics

- `acceptable_difference` column rendered as a badge.
- Bar chart: grey bars for accepted columns; clicking a grey bar (or badge)
  opens a popup with the `reason`, `example_left`, `example_right` from
  `accepted_differences.csv`.

## Non-goals

No build step, no framework, no external CDN (must work offline). Modern
evergreen browsers only.
