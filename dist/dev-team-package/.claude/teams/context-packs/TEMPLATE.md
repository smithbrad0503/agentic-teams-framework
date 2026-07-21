# Context Pack — <team>
> Injected into every <team> team-run agent prompt. POINTERS, NOT CONTENT.
> Staleness: refreshed <YYYY-MM-DD> (manual seed) · refresh: librarian after merges touching ownership zones

<!--
  The context pack is the framework's primary token lever. It replaces cold
  re-exploration on every agent spawn. Rules that earn their keep:

  1. POINTERS OVER CONTENT — say WHERE to Read, never paste code. "Auth lives in
     `src/auth/`" beats pasting the auth module.
  2. TRIP-WIRES OVER TUTORIALS — capture the things that BURNED you (a naming
     convention, a migration-proof requirement, a gitignore trap), not generic
     best practices the model already knows.
  3. HARD CAP ~12,000 chars (~3k tokens). A bloated pack is worse than no pack —
     it crowds out the actual task. The CI test enforces this cap.
  4. STALENESS HEADER above is mandatory — a stale pack silently misleads every
     agent that trusts it. Update the date whenever you edit; wire a librarian
     refresh after merges that touch this team's ownership zones.

  Keep the three required section headings below (## Map / ## Trip-wires /
  ## Current state) — the pack test asserts they exist.
-->

## Map
<!-- Where things live. One line per zone. Backtick any directory path — the pack
     test verifies backticked `dir/` pointers actually exist in the repo. -->
- <subsystem>: `path/to/dir/` — one-line description of what's there and how it's wired
- <subsystem>: `path/to/other/` — pointer, not a paste
- Tests: `tests/` — where this team's tests live; regression pins in `tests/regression/`
- Project commands: formatter / linter / type-checker / test runner invocations the
  guardrails reference (e.g. `make lint`, `pytest -q`, `npm test`)

## Trip-wires
<!-- The lessons paid for in debugging. Each line = one landmine + how to avoid it. -->
- <the convention that, if violated, silently corrupts data or breaks a contract>
- <the "looks-optional-but-is-load-bearing" step someone skipped once>
- <the shared local resource that throws transient errors under parallel agents —
  rerun the targeted slice before treating it as a real failure>

## Current state
<!-- What is in flight RIGHT NOW that a fresh agent would not know. Keep it short and
     prune aggressively — this section rots fastest. -->
- <feature/subsystem>: <status — e.g. "landed but flag-dark", "migration pending">
- <known in-flight work that affects how you touch these files>
