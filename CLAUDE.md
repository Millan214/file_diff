# compare-dataframes

This file is a router only. All project knowledge lives in `.claude/`.

| Topic | Where |
|---|---|
| Original spec (verbatim, source of truth) | `req.txt` |
| Distilled requirements | `.claude/docs/spec.md` |
| Resolved ambiguities & decisions log | `.claude/docs/decisions.md` |
| Architecture, gate contract, exit codes | `.claude/docs/architecture.md` |
| Implementation plan + model per step | `.claude/docs/plan.md` |
| Dashboard (main.html) design | `.claude/docs/dashboard.md` |
| Per-layer specs | `.claude/layers/layer_1_read.md` … `layer_4_compare_values.md` |
| Shared utilities spec | `.claude/utils/README.md` |
| Subagents for building this project | `.claude/agents/` |
| Git remote, branching (gitflow), commit conventions | `.claude/docs/git-workflow.md` |

Rules that apply everywhere:
- Data transformations are pure functions chained with `df.pipe` (see `.claude/docs/architecture.md#code-style`).
- Every layer follows the run → export → report → gate contract; never gate before artifacts are written.
- Package management is `uv` only.
- Git: gitflow branching (`feature/*` off `develop`); commits prefixed `FEAT:`, `FIX:`, `TEST:`, `CHORE:` (see `.claude/docs/git-workflow.md`).
