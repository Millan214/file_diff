# Layer 3 — compare_rows

## Purpose
Match rows by `KEY_COLUMNS` (composite allowed, D2); classify as left-only /
inner / right-only; find duplicate keys.

## run
1. Duplicates: keys appearing >1 time in a file. Collect per side.
2. Outer-merge key sets (dedup'd) → classify `left_only`, `inner`, `right_only`.
3. Inner keys exclude any key duplicated in either side (D8).
4. Verdict: `success` if no left_only/right_only/duplicates;
   `completed-with-differences` otherwise; `failed` only if `inner` is empty
   (nothing left to compare — layer 4 would be meaningless).

Pure functions: `find_duplicates`, `classify_keys`, `row_verdict`.

## Exports (CSV/TXT)
One row per non-inner key:
`<key columns…>, status` (status ∈ left_only / right_only / duplicate_left /
duplicate_right / duplicate_both). Summary counts land in the manifest and PDF.

## PDF report
Standard header + verdict banner + summary table + **horizontal bar chart**:
left-only, inner, right-only counts, and duplicates (D14).

## Gate
`failed → STOP` (exit 3 via D11 when it is the first non-success). Otherwise
CONTINUE with inner keys (D1) — even when differences were found.
