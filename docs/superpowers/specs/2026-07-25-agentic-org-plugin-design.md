# agentic-org v1 — Materializing Claude Code Plugin

**Date:** 2026-07-25
**Status:** Approved design, pre-implementation
**Repo:** `smithbrad0503/agentic-teams-framework` (this repo becomes the plugin)

## Purpose

Turn the agentic-teams framework into an installable Claude Code plugin named
**`agentic-org`**. A user installs it, runs an interview wizard, and gets a
customized agentic org materialized into their project — agents, teams, context
packs, shared memory, and the gated delivery pipeline.

Primary goal: public credibility asset for the consulting practice, proven
through real client builds. Secondary: faster spin-up of Brad's own projects.
Not a paid product in v1.

## Core decisions (settled during brainstorming)

| Decision | Choice |
|---|---|
| V1 scope | Plugin packaging + `/org-init` generator wizard |
| Generation strategy | Curate + customize from a library of ~25 proven agent identities (no from-scratch synthesis) |
| Shared memory | Org-level memory layer alongside existing per-team memory |
| Workflows | Ship proven `team-run.js` pipeline + 2–3 recurring-workflow recipes; no workflow *generation* in v1 |
| Architecture | **Materializing plugin**: plugin carries the library and tools; `/org-init` writes a project-owned org into the project's `.claude/` |
| Repo strategy | This repo becomes the plugin (manifest + marketplace file added); manual-copy path from the README remains supported |

## Architecture

```
PLUGIN (installed once, via marketplace)
  .claude-plugin/plugin.json      name: agentic-org
  library/agents/                 ~25 curated agent identities
  library/teams/, context-packs/, memory/   templates
  library/workflows/              team-run.js + recipes
  skills: /org-init, /org-update, /team
        |
        |  /org-init interview
        v
PROJECT .claude/  (owned by the user; survives plugin uninstall)
  agents/          customized copies with filled Project Context blocks
  teams/*.yaml     generated rosters + ownership zones
  teams/context-packs/   drafted from a real codebase scan
  org-memory/      decisions.md, architecture.md, lessons.md
  workflows/       team-run.js + selected recipes
  teams/model-routing.yaml   mapped to models the user's setup exposes
```

The project owns its materialized org. Clients keep a working org even if the
plugin is removed. Library improvements reach existing orgs only through an
explicit `/org-update`.

## Components

### 1. Agent library

The existing agent set becomes `library/agents/`. Each agent file gains a
marked **Project Context injection block** (clearly delimited section) that the
wizard fills during materialization. Customization is structural — the wizard
edits inside the block, not by rewriting the identity. Roster metadata
(`AGENTS.md`) maps agents to business functions (delivery, product, growth,
business-ops) so the wizard can select by need.

### 2. `/org-init` wizard (skill)

Interview → select → materialize:

1. **Interview:** business/product type, tech stack, which functions the user
   needs, model tiers available, repo/CI facts (detects `git`, `gh`, worktree
   support).
2. **Select:** choose the roster and team structure from the library based on
   answers.
3. **Materialize:** write customized agents, team yamls, context packs
   (drafted from an actual scan of the user's codebase — pointers and
   trip-wires, honoring the ~12k-char cap), org-memory scaffold, workflows,
   model-routing mapped to the user's model identifiers, and `.gitignore`
   entries for runtime state.

Every generated file gets a **provenance header**: library version + source
template path. This is what makes `/org-update` diffable.

Idempotence: if an org already exists, the wizard offers **update** (delegate
to `/org-update`) or **extend** (add teams/agents) — never silent overwrite.

### 3. `/org-update` (skill)

Re-syncs library improvements into a materialized org. Uses provenance headers
to compute the baseline, shows per-file diffs, and applies only what the user
accepts. Never overwrites user customizations silently.

### 4. Org memory layer

`.claude/org-memory/` with three capped files (same philosophy as context
packs — small, curated, high-signal):

- `decisions.md` — cross-team decisions with dates and rationale
- `architecture.md` — durable facts about the system
- `lessons.md` — cross-team lessons (per-team lessons stay in team memory)

`team-run.js` changes: inject org-memory content at the **decompose** and
**review** stages; at run end, append **candidate** entries to a staging
section. The cockpit (human-driven session) curates candidates into the files
— runs never auto-commit to org memory.

### 5. Workflow recipes

Generalize 2–3 proven recurring workflows from the BlitzAI implementation into
`library/workflows/recipes/`: health-check, audit, retro. Shipped as adaptable
templates the wizard offers during materialization; not auto-generated.

## Data flow

Install plugin → `/org-init` interview → org materialized in project
`.claude/` → `/team dispatch <team> <ticket> "<brief>"` → gated, CI-green PR
(runner never merges) → run outcomes appended to team memory + org-memory
candidates → human curates memory, merges PR → `/org-update` when the library
evolves.

## Error handling

- **Prerequisites:** wizard checks git repo, `gh` auth, and worktree support
  upfront; failures produce plain-language fixes, not mid-run breakage.
- **Model routing:** if a configured tier is unavailable, fall back to the
  strongest available model with a warning. The review gate never silently
  demotes (preserves the framework's existing invariant).
- **Existing org detected:** offer update/extend; never overwrite.
- **Partial materialization:** the wizard writes to a staging directory and
  moves files into place only after all generation succeeds.

## Testing

- Extend the existing pytest suite: run the wizard against 2–3 **fixture
  project types** and assert the materialized org passes the same
  schema/hygiene tests as hand-written config (team defs, context packs,
  state).
- Validate `plugin.json` and `marketplace.json` shape.
- **Dogfood gate:** one full real-project run (materialize + dispatch + gated
  PR) on one of Brad's projects before any public announcement.

## Out of scope for v1 (v2 candidates)

- Dynamic workflow *generation* from a description
- Structured/queryable knowledge base (org memory stays file-based)
- Industry-specific agent packs
- Paid tiers / commercial licensing
- Cross-project (portfolio-level) org memory
