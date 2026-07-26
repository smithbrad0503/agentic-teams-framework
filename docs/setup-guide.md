# Setup Guide — adopting the Agentic Teams Framework

Step-by-step adoption for a new project. End state: you dispatch a named team at a
ticket from one cockpit session, and it returns a code-reviewed, CI-green pull request
that a human approves and merges.

> **Fastest path:** install the plugin and let the wizard do steps 1–4 for you —
> `/plugin marketplace add smithbrad0503/agentic-teams-framework`, then
> `/plugin install agentic-org@agentic-teams`, then run `/org-init` in your project.
> The manual steps below remain fully supported and describe exactly what the wizard
> generates.

## Prerequisites

- **Claude Code** with the **Workflow** tool available (the runner is a Workflow script,
  `.claude/workflows/team-run.js`).
- **`git`** and the **`gh` CLI**, authenticated against your repo host — the runner opens
  PRs and watches CI via `gh`.
- **`jq`** — the `/team` command uses it to maintain `state/board.json`.
- **A default branch** the runner can branch from and open PRs against (e.g. `main`).
- Optional: **Python + pytest + PyYAML** if you want to run the framework's own schema
  tests (`tests/`).

## 1. Install

Copy the framework's `.claude/` tree into your project's `.claude/` (merge if you already
have one), plus the `docs/` and `tests/` if you want them tracked:

```bash
# from the framework package root, into your project:
cp -R .claude/workflows/team-run.js   YOUR_PROJECT/.claude/workflows/
cp -R .claude/commands/team.md        YOUR_PROJECT/.claude/commands/
cp -R .claude/teams                   YOUR_PROJECT/.claude/
cp -R .claude/agents                  YOUR_PROJECT/.claude/
```

Add the state-ignore lines to your project's `.gitignore`:

```
.claude/teams/state/*
!.claude/teams/state/.gitkeep
```

Track the definitions and memory, but not the runtime state — that split is what keeps the
board/telemetry from polluting your git history while your org chart stays version-controlled.

## 2. Map the model tiers

Open `.claude/teams/model-routing.yaml`. The model names are **placeholders**
(`strong` / `mid` / `cheap`). Replace them with the model identifiers your Claude Code
setup exposes:

- `strong` → your most capable model (used for decompose and the review gate).
- `mid` → a balanced model (implement, tests, docs, revision-fix).
- `cheap` → a fast/cheap model (mechanical: state writes, formatting, doc sync).

Keep the **shape**: decompose and review on the strongest tier; the review gate is never
demoted. `effort` is one of `low | medium | high | xhigh | max`.

## 3. Define your first team

Copy `.claude/teams/TEMPLATE.yaml` to `.claude/teams/<team>.yaml` (e.g. `backend.yaml`).
Fill in:

- `name` — must equal the filename stem.
- `roster.lead` / `specialists` / `test` — names from `.claude/agents/` (each must have a
  matching `<name>.md`, or the schema test fails).
- `ownership` — the file zones this team may edit. The runner confines every mutating stage
  to these paths plus `tests/` and `docs/`; anything else is reported as `outOfZoneNeeds`,
  never silently changed. This is how cross-team collisions surface.
- `context_pack` — points at the pack you write next.
- Leave `routing: {}` to inherit all global defaults until you have evidence to override.

## 4. Write the context pack

Copy `.claude/teams/context-packs/TEMPLATE.md` to `context-packs/<team>.md`. This is the
single highest-leverage token investment — it replaces cold re-exploration on every agent
spawn. Rules:

- **Pointers, not content** — say *where* to Read; never paste code.
- **Trip-wires over tutorials** — capture the things that have burned you (a naming
  convention, a migration-proof requirement, a gitignore trap), not generic best practices.
- **Hard cap ~12,000 chars** (CI enforces it) — a bloated pack crowds out the actual task.
- **Keep the staleness header current** — a stale pack silently misleads every agent.
- Keep the three required headings: `## Map`, `## Trip-wires`, `## Current state`.

Also create `.claude/teams/memory/<team>.md` from the memory `TEMPLATE.md` (just the seed
heading — runs append to it).

## 5. Dispatch

From your cockpit session:

```
/team dispatch <team> <ticket> "<concrete brief>" [small|medium|large]
```

What happens (see `.claude/commands/team.md` for the exact steps):

1. **Sync** — the cockpit fetches origin so you never branch from a stale base.
2. **Register** — a board entry + `dispatched` event are written to `state/`.
3. **Resolve config** — team yaml + routing + pack + memory are merged into a `config`.
4. **Invoke** — `team-run` runs in the background through its stages:
   decompose → implement → test → docs → review gate → CI gate → report.
5. **Relay** — on completion you get status, PR link, and rounds. **Nothing is merged.**

Check progress any time with `/team status` (renders from the board with zero agent spawns).

## 6. The human approval gate

**The runner opens a PR and stops. It never merges and never pushes to the default branch.**
Merge approval is always a human decision. The runner also refuses to execute stateful/outward
operations (production DB writes, deploys, queue drains) — it documents them as ops steps in
the PR body instead. Review the PR, and merge it yourself when satisfied.

## 7. Terminal states you'll see

| Status | Meaning |
|---|---|
| `pr-ready` | Review passed and CI is green. PR awaits your merge. |
| `ill-specified` | Decompose judged the brief too vague and returned questions. Refine and re-dispatch — this is a cheap, good failure. |
| `review-stalemate` | 3 review rounds without convergence. Usually a decompose problem; inspect the unresolved findings. |
| `needs-human` / `blocked` | A stage failed twice, or CI stayed red after fixes. The run stops and reports; no half-finished push is left behind. |

## 8. Dry-run / crash notes

- **Dry run:** invoking `team-run` with a `fixtures` arg (a map of stage-label → canned
  result) runs the full stage skeleton with no real agents and no state writes, returning the
  stage trace. Use it to validate phase ordering and gate wiring.
- **Crash resume:** state is persisted on every early exit, so a crashed run leaves a valid
  board entry and telemetry. Resume-from-last-stage (`resumeFromRunId`) is the planned
  enhancement; until then, an orphaned worktree/branch is *flagged* by `/team status`, never
  auto-deleted — it may be a resumable run.
