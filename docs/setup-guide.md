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

The file's top-level `fallback:` entry is not a stage class — it is the route a failed stage's
single retry escalates to, so a model-level failure (capacity, availability) is retried
somewhere else instead of on the model that just failed. Map it to a strong, reliably
available model.

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
- `type` / `output` / `gates` — the team's mode, and they must agree:
  `delivery` + `pr` + `gates: [code-review, ci-green]` for a team that ships code, or
  `advisory` + `document` + `gates: [critique]` for a team whose deliverable is a written
  recommendation. An advisory run opens no PR, so `ci-green` names a check it can never
  satisfy; the validator rejects the combination. On an advisory team `roster.test` is the
  **gate seat** — the non-author who critiques the document — and it must not be the lead.
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

The size argument is a telemetry label for slicing cost and rounds by ticket size; it sets no
budget and changes no behaviour.

What happens (see `.claude/commands/team.md` for the exact steps):

1. **Sync** — the cockpit fetches origin so you never branch from a stale base.
2. **Register** — a board entry + `dispatched` event are written to `state/`.
3. **Resolve config** — team yaml + routing + pack + memory are merged into a `config`.
4. **Invoke** — `team-run` runs in the background through the stages its output mode defines.
   Delivery (`output: pr`): decompose → implement → test → docs → review gate → CI gate →
   report. Advisory (`output: document`): advise → critique gate (multi-lens, by a
   non-author, each finding attacked by two refuters) → revise → report, looping the gate
   within `maxCritiqueRounds`.
5. **Relay** — on completion you get status, PR link, and rounds. **Nothing is merged.**
   An advisory run has no PR link: you get its `verdict`, the document path, open questions,
   and anything flagged as needing your approval.

Check progress any time with `/team status` (renders from the board with zero agent spawns).

## 6. The human approval gate

**The runner opens a PR and stops. It never merges and never pushes to the default branch.**
Merge approval is always a human decision. The runner also refuses to execute stateful/outward
operations (production DB writes, deploys, queue drains) — it documents them as ops steps in
the PR body instead. Review the PR, and merge it yourself when satisfied.

An advisory run takes the same discipline further: it writes its document into the team's
ownership zones and stops, creating **no branch and no PR at all**, and it is forbidden from
editing application source. Nothing is committed — the document waits in your working tree.

## 7. Terminal states you'll see

| Status | Meaning |
|---|---|
| `pr-ready` | Review passed and CI is green. PR awaits your merge. |
| `ill-specified` | Decompose judged the brief too vague and returned questions. Refine and re-dispatch — this is a cheap, good failure. |
| `review-stalemate` | The review budget (3 rounds) ran out and a confirm-only re-check found the outstanding items still unresolved. Usually a decompose problem; inspect the unresolved findings. |
| `needs-human` / `blocked` | A stage failed twice, or CI stayed red after fixes, or the review side cleared but CI was never verified green. The run stops and reports; no half-finished push is left behind. |
| `document-ready` | **Advisory only.** The critique gate found nothing standing and lost no stage: `verdict: APPROVED`. The document is in your working tree, uncommitted. |
| `critique-stalemate` | **Advisory only.** The critique budget ran out with must-fix findings still standing: `verdict: REVISE`. Read the standing findings — like `review-stalemate`, this usually means the brief was wrong, not the writer. |
| `needs-human` (advisory) | `verdict: INCOMPLETE` — a gate stage died (a critique lens, both refuters on a finding, or a revision), so the document was never fully checked. **Re-run before acting on it.** A degraded run never reports as a clean document. |

The review gate and the CI gate carry separate budgets (`maxReviewRounds`, `maxCiAttempts`,
capped overall by `maxGateRounds`), so a mechanical CI fix does not consume a review round.
Each run's telemetry records `verifiedAtHead`: `true` means a gate checked the current branch
HEAD to produce that status, `false` means the run bounded out and the status may predate the
last fix that was pushed.

## 8. Dry-run / crash notes

- **Dry run:** invoking `team-run` with a `fixtures` arg (a map of stage-label → canned
  result) runs the full stage skeleton with no real agents and no state writes, returning the
  stage trace. Use it to validate phase ordering and gate wiring.
- **Crash resume:** state is persisted on every early exit, so a crashed run leaves a valid
  board entry and telemetry. Resume-from-last-stage (`resumeFromRunId`) is the planned
  enhancement; until then, an orphaned worktree/branch is *flagged* by `/team status`, never
  auto-deleted — it may be a resumable run.
