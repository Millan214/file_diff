# Implementation plan

Steps are ordered by dependency; each is independently verifiable. Model
recommendations balance capability vs cost: **Haiku 4.5** for mechanical work,
**Sonnet 5** for standard implementation, **Opus 4.8** for semantics-heavy or
review work. Agent definitions for these roles: `.claude/agents/`.

| # | Step | Model | Why this model |
|---|------|-------|----------------|
| 0 | Scaffold: `uv init`, pyproject deps (pandas, charset-normalizer, fpdf2, matplotlib, pytest), folder tree, empty modules, `config.py` skeleton | **Haiku 4.5** | Purely mechanical; the structure is fully specified in spec.md |
| 1 | Test fixtures: 4–6 CSV pairs (identical; column drift; row drift + duplicates; value drift; encoding conflict; empty-common-set) 5–20 rows each | **Haiku 4.5** | Rote data authoring from the layer specs' edge-case lists |
| 2 | Utils: `ExecutionContext`, artifact writers, `encoding.py`, `keys.py` + tests | **Sonnet 5** | Standard plumbing with a few sharp edges (collision suffix, fixed-width TXT) |
| 3 | PDF engine: `ReportBuilder`, verdict banner, tables, `barh_chart` with grey-mask | **Sonnet 5** | fpdf2+matplotlib integration is fiddly but well-trodden; load `dataviz` skill |
| 4 | Layer 1 read (+gate, tests) | **Sonnet 5** | Encoding policy D4 already nailed down in docs |
| 5 | Layer 2 compare_columns (+gate, tests) | **Sonnet 5** | Set logic + dtype table; gate rules D2/D5 are specified |
| 6 | Layer 3 compare_rows (+gate, tests) | **Sonnet 5** | Composite-key merge classification; D8 exclusion rule needs care |
| 7 | Layer 4 compare_values (+gate, tests) | **Opus 4.8** | The value-equality matrix (D9: NaN, numeric coercion, tolerances) × accepted-differences policy (D3) is where subtle correctness bugs live |
| 8 | Orchestrator `main.py`: layer loop, contract enforcement (export/report before gate), manifest + executions.json, exit codes D11, crash handling | **Sonnet 5** | Glue code against a written contract (architecture.md) |
| 9 | Dashboard `main.html`: manifest loading, sidebar/header, filterable tables, charts, accepted-reason popup | **Opus 4.8** | Single-file vanilla-JS app with Excel-like filtering, virtualization, and CSV parsing — the largest uninterrupted piece of logic in the project |
| 10 | End-to-end verification: run all fixture pairs through the CLI, check artifacts/exit codes/manifest; serve dashboard and click through | **Sonnet 5** | Execution + assertion against specs; use the `verify` skill |
| 11 | Final review pass against req.txt + decisions.md; `/code-review` | **Opus 4.8** (or Fable 5 if available) | Cross-cutting spec-compliance auditing pays for the strongest model |

## Sequencing notes

- 0–1 can run in one session; 2–3 unblock everything else.
- 4–7 are independent of each other once 2–3 exist — parallelizable across
  sessions/agents (each layer only *consumes* prior layers' result shape, which
  is fixed in architecture.md).
- 9 only needs the manifest schema (dashboard.md) + fixture outputs from 10's
  first run; build 8 before 9.

## Definition of done per step

Every step: code + tests pass (`uv run pytest`), pure functions piped per
architecture.md#code-style, no layer writing files outside its folder.
Steps 4–7 additionally: all three artifacts produced for both the success and
failure fixture, gate decision matches the layer spec table.
