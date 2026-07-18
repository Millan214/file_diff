# Decisions log

Ambiguities found in `req.txt` and how they were resolved. "User-confirmed"
answers were chosen by the user on 2026-07-18; "default" entries are proposed
interpretations — challenge them here before changing code.

## User-confirmed

**D1 — Layer 3 gate: continue with inner rows.**
The spec says "if the rows are different by id, the script shall end", which
contradicts layer 2's continue-with-common-columns behavior. Resolved: layer 3
reports left-only/right-only rows and duplicates, marks its verdict
`completed-with-differences`, and the pipeline continues to layer 4 using only
the inner (matched) rows.

**D2 — Key columns come from config; composite keys allowed.**
`config.py` declares `KEY_COLUMNS: list[str]`. Hard failure in layer 2's gate if
any key column is absent from the common-columns set. Auto-detection and
"first column" conventions were rejected.

**D3 — Accepted-only differences = success.**
If every layer-4 difference is in an accepted column, exit code is 0 and the PDF
verdict is green. Accepted differences are still listed, flagged
`acceptable_difference=True`, and drawn as grey bars.

**D6 — Dashboard = static main.html + per-run manifest.json + local server.**
Plain `file://` HTML cannot fetch CSVs or list directories. Each run writes
`manifest.json`; a root-level `executions.json` index is rebuilt on every run so
the dropdown can list executions. Served via `python -m http.server` from repo
root (a `serve` helper command is provided).

## Defaults (proposed by Claude, not yet user-confirmed)

**D4 — Encoding policy.**
Detection via `charset-normalizer`. ASCII is treated as UTF-8 (ASCII ⊂ UTF-8, a
pure-ASCII file must not fail against a UTF-8 file). Hard failure only when a
file cannot be decoded or when the two normalized encodings differ
(e.g. utf-8 vs cp1252 with non-ASCII bytes). Detected encodings always appear in
every layer's report header.

**D5 — Layer 2 internal contradiction resolved as soft gate.**
`req.txt` says both "shall end if columns differ" and "shall continue with
common columns". Resolved: report differences, continue with the common set;
hard stop only if the common set is empty or missing a key column (see D2).
Mirrors D1.

**D7 — Dtype mismatches do not gate.**
CSVs carry no types; pandas inference is data-dependent (one empty cell turns
int64 into float64). Dtype comparison is reported in layer 2 (per-column dtype
left/right + match flag). Mismatched-dtype columns stay in the common set; in
layer 4 they are compared with normalization (see D9).

**D8 — Duplicate keys: reported and excluded, not fatal.**
Rows whose key is duplicated in either file are counted (bar chart), listed in
layer 3's exports, and excluded from layer 4 (pairing would be ambiguous).
Consistent with D1's soft-gate philosophy.

**D9 — Value equality semantics.**
NaN == NaN is True (both missing = no difference). Numeric comparison: compare
as numbers when both sides parse as numeric (so `1` == `1.0`), with optional
per-column absolute tolerance in config (default 0 = exact). Everything else:
exact string comparison after stripping trailing whitespace. Dates are NOT
format-normalized (out of scope; an accepted-differences entry can cover it).

**D10 — Execution folder name.**
`execution=<YYYY-MM-DD_HH-MM-SS>` (no literal `(hash)` — parentheses in the
spec's `execution(hash)=` read as "hash goes here", but the example value is a
timestamp). An 8-char SHA-256 content hash of both input files is stored inside
`manifest.json`, not in the folder name. Same-second collision appends `_1`.

**D11 — Exit codes.**
`0` all layers passed (accepted-only diffs count as passed, D3). Otherwise the
exit code is the number of the first layer whose verdict was not success:
`1` read failure, `2` column hard-failure, `3` row differences/duplicates,
`4` non-accepted value differences. Per-layer verdicts are in `manifest.json`;
the exit code is a summary, not the full story.

**D12 — TXT export format.**
The TXT is the same table as the CSV rendered fixed-width
(`DataFrame.to_string`-style) with a small header (files, encodings, verdict,
timestamp). "New column" requirements apply to it exactly as to the CSV.

**D13 — Inputs are CSV only** (as in the spec's example tree). Delimiter `,`,
header row required, configurable in `config.py`. Excel support is out of scope.

**D14 — Chart orientations.**
Layer 3: horizontal bars (left / inner / right / duplicates) as specified.
Layer 4: the spec says "vertical graph … on a horizontal bar graph"
(contradictory); resolved as horizontal bars — column names on the y-axis,
difference counts on the x-axis — which stays readable with many columns.
