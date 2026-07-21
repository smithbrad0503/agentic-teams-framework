# Context Pack — dev
> Injected into every dev team-run agent prompt. POINTERS, NOT CONTENT.
> Staleness: refreshed on install (seed) · refresh this whenever the map or trip-wires drift.

<!--
  THIS IS A SEED. Replace the placeholders below with your repo's real map, real
  landmines, and real in-flight state. The value of the pack is proportional to how
  specific and current it is. Rules: pointers over pasted code; trip-wires over
  tutorials; hard cap ~12,000 chars; keep the staleness header honest.
-->

## Map
- Application code: `src/` — describe the top-level layout (entry point, where routes/handlers live, where the data models live, where shared services live)
- Tests: `tests/` — where unit/integration tests live; put high-severity regression pins in `tests/regression/`
- Project commands the guardrails rely on — fill these in for your stack, e.g.:
  - format: `<your formatter>` (e.g. `ruff format` / `prettier -w`)
  - lint: `<your linter>` (e.g. `ruff check` / `eslint`)
  - type-check: `<your type checker>` (e.g. `mypy` / `tsc --noEmit`)
  - test: `<your test runner>` (e.g. `pytest -q` / `npm test`)

## Trip-wires
<!-- Replace with the things that have actually burned your team. Examples of the SHAPE: -->
- <a naming/schema convention that silently corrupts data if violated>
- <a "looks-optional-but-load-bearing" migration/backfill step that must be proven, not assumed>
- <a build/gitignore trap — e.g. one-shot scripts must live under a specific dir to be included>
- If a shared local test resource (DB, cache) throws transient errors under parallel agents,
  rerun the targeted slice before treating it as a real failure.

## Current state
<!-- Prune this hard — it rots fastest. What would a fresh agent not know today? -->
- <feature/subsystem>: <status — e.g. "landed but behind a flag", "migration pending">
