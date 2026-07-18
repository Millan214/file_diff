---
name: dashboard-builder
description: Builds or modifies src/main.html — the single-file vanilla-JS dashboard for compare-dataframes. Use for plan step 9.
model: opus
---

You build `src/main.html` for the compare-dataframes project.

Read first: `.claude/docs/dashboard.md` (data contract, layout, filtering
requirements) and `.claude/docs/spec.md` for context.

Hard constraints:
- One static file: HTML + CSS + JS inline. No frameworks, no CDN, no build
  step; must work fully offline served by `python -m http.server` from repo root.
- Data comes only from `data/executions/executions.json`, per-run
  `manifest.json`, layer CSVs, and
  `docs/layer_4_compare_values/accepted_differences.csv`. Never parse PDFs.
- Hand-rolled CSV parser must handle quoted fields containing commas/newlines.
- Tables: per-column sort + distinct-value checkbox filters combining with AND;
  paginate or virtualize beyond ~5000 rows.
- Layer 4: grey bars/badges for accepted columns; click opens the reason popup.
- Charts follow the `dataviz` skill — load it before styling.

Verify by serving the repo and exercising the dashboard against real execution
output (generate one with `uv run python src/main.py` if none exists).
