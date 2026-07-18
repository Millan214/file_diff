# Layer 2 — compare_columns

## Purpose
Compare column sets and dtypes; hand the common columns to layer 3.

## run
1. `left_only = cols(left) - cols(right)`, `right_only = cols(right) - cols(left)`,
   `common = ordered intersection` (order = left file's column order).
2. Dtype table for common columns: `column, dtype_left, dtype_right, dtype_match`.
   Mismatches are informational only (D7).
3. Verdict: `success` if no left_only/right_only and all dtypes match;
   `completed-with-differences` if sets differ or dtypes mismatch but common set
   is usable; `failed` if `common` is empty or any `KEY_COLUMNS` entry (D2) is
   missing from `common`.

Pure functions: `split_columns`, `dtype_table`, `column_verdict`.

## Exports (CSV/TXT)
One row per column across the union:
`column, in_left, in_right, dtype_left, dtype_right, dtype_match, status`
(status ∈ common / left_only / right_only).

## PDF report
Standard header + verdict banner + three tables (left_only, right_only, common
with dtypes) + explicit list of the common columns the pipeline continues with.

## Gate
`failed → STOP` (exit code 2). `completed-with-differences` and `success` → CONTINUE (D5).
