# Agents

Subagent definitions for building this project, aligned with the plan steps in
`.claude/docs/plan.md`:

- **layer-builder** (Sonnet) — implements one layer or utils module per its
  `.claude/layers/`/`.claude/utils/` spec. Plan steps 2–8. Give it exactly one
  component per invocation.
- **dashboard-builder** (Opus) — builds `src/main.html`. Plan step 9.
- **spec-auditor** (Opus, read-only) — audits code against req.txt +
  decisions.md. Plan step 11 / after big changes.

Mechanical steps 0–1 (scaffold, fixtures) don't need a dedicated agent — run
them inline or with a Haiku-model general agent.
