# Git workflow

**Remote:** https://github.com/Millan214/file_diff.git (origin)

## Branching model — gitflow

- `main` — production-ready history; every commit here is releasable.
- `develop` — integration branch; default branch for day-to-day work.
- `feature/*` — one branch per feature or task, branched from `develop`,
  merged back into `develop` (e.g. `feature/layer-3-compare-rows`,
  `feature/dashboard-filters`).
- `release/*` — branched from `develop` when preparing a release, merged into
  both `main` and `develop`. Use only when a release needs stabilization time.
- `hotfix/*` — branched from `main` for urgent production fixes, merged into
  both `main` and `develop`.

Day-to-day implementation work happens on `feature/*` branches off `develop`;
`main` only receives merges via `release/*` or `hotfix/*`.

## Commit message prefixes

Every commit subject starts with one of:

| Prefix | Use for |
|---|---|
| `FEAT:` | New functionality (a layer, a utility, a dashboard feature) |
| `FIX:` | Bug fixes |
| `TEST:` | Adding or updating tests/fixtures |
| `CHORE:` | Tooling, config, scaffolding, docs, non-functional changes |

Example: `FEAT: implement layer 3 compare_rows gate`
