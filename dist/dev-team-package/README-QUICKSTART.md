# Dev Team — Quickstart (15 minutes)

A self-contained Claude Code package that gives you **one software-developer team** you can
dispatch at a ticket. It returns a **code-reviewed, CI-green pull request** and stops — it
**never merges**. You review and merge yourself.

This is the developer-only subset of the Agentic Teams Framework: one deterministic runner,
a ready-to-use `dev` team, and the 10 engineering agents it needs. No product/marketing/legal
roster, no external dependencies beyond the tools listed below.

## What you get

```
.claude/
  workflows/team-run.js        the runner: decompose → implement → test → docs → review → CI → report
  commands/team.md             /team dispatch | status
  teams/
    dev.yaml                   ready-to-use team (lead: tech-lead; specialists: backend/frontend/api/database; test: qa-tester)
    model-routing.yaml         per-stage model tiers (PLACEHOLDERS — you map these, step 2)
    TEMPLATE.yaml              copy this to add more teams
    context-packs/dev.md       your repo briefing (a seed — customize it, step 4)
    context-packs/TEMPLATE.md
    memory/dev.md              grows as runs record lessons
    memory/TEMPLATE.md
    state/.gitkeep             runtime board/telemetry (gitignored)
  agents/                      tech-lead, backend-expert, frontend-expert, api-expert,
                               database-expert, qa-tester, code-reviewer, debug-expert,
                               docs-author, github-expert  (+ AGENTS.md registry)
```

## Fastest install: hand it to an agent

If you use Claude Code, skip the manual steps: open a session in your target repo and say
*"Read docs/AGENT-IMPLEMENTATION-GUIDE.md from the dev-team package and implement it for
this repo."* The guide walks the agent through discovery, install, model mapping, team
config, a fixture dry run, and a supervised first dispatch — asking you only the questions
it can't answer from the repo (model names, ownership zones, trip-wires).

## Prerequisites

- **Claude Code** with the **Workflow** tool.
- **`git`** + the **`gh` CLI**, authenticated against your repo host (the runner opens PRs and
  watches CI via `gh`).
- **`jq`** (the `/team` command maintains the board with it).
- A **default branch** (e.g. `main`) to branch from and open PRs against.

## Install (5 min)

1. Copy this package's `.claude/` into your repo's `.claude/` (merge if you already have one):
   ```bash
   cp -R dev-team-package/.claude/. YOUR_REPO/.claude/
   ```
2. Add to `YOUR_REPO/.gitignore`:
   ```
   .claude/teams/state/*
   !.claude/teams/state/.gitkeep
   ```

## Map the models (3 min) — REQUIRED

Open `.claude/teams/model-routing.yaml`. The model names are **placeholders**:
`strong`, `mid`, `cheap`. **Replace them with the model identifiers your organization has
access to.** Every org exposes a different set of models — pick:

- `strong` → your most capable model. Used for **decompose** (planning) and the **review gate**.
- `mid` → a balanced model. Used for implement, tests, docs, revision-fix.
- `cheap` → a fast/inexpensive model. Used for mechanical work (state writes, formatting).

Keep the **shape**, whatever your models are called: planning and review get the strongest
tier, and **the review gate is never dropped to a cheaper tier** — that gate is what stops a
plausible-but-wrong change from shipping. `effort` is one of `low | medium | high | xhigh | max`.

## Point the team at your repo (2 min)

Edit `.claude/teams/dev.yaml` → `ownership:` so it lists the directories this team may edit
(e.g. `src/`, `app/`, `services/`). The runner confines every change to these zones plus
`tests/` and `docs/`; anything else is reported, not silently changed.

Then open `.claude/teams/context-packs/dev.md` and fill in the seed: where your code lives
(`## Map`), the landmines that have burned your team (`## Trip-wires`), and your project's
format / lint / type-check / test commands. This pack is injected into every agent so they
don't re-explore your repo cold — it's the single highest-leverage thing you'll write.

## First dispatch (2 min)

From your Claude Code cockpit session:

```
/team dispatch dev TICKET-123 "Add a paginated GET /v2/items endpoint with input validation and tests" medium
```

The run works in the background through decompose → implement → test → docs → review gate →
CI gate, and returns a PR link with its status. Track it any time:

```
/team status
```

## The one rule that never changes

**The runner opens a pull request and stops.** It does not merge, does not push to your default
branch, and does not run deploys or production data operations (it documents those as ops steps
in the PR body). A human reviews and merges. That is the entire safety model — keep it.

## Statuses you'll see

| Status | Meaning |
|---|---|
| `pr-ready` | Review passed, CI green. Your PR is waiting for you to merge. |
| `ill-specified` | The brief was too vague; decompose returned questions. Refine and re-dispatch (a cheap, good failure). |
| `review-stalemate` | 3 review rounds without convergence — usually a too-big or unclear brief. |
| `needs-human` / `blocked` | A stage failed twice or CI stayed red; the run stopped cleanly and reported. No half-finished push is left behind. |

## Adding more teams later

Copy `.claude/teams/TEMPLATE.yaml` to a new `<team>.yaml`, give it a roster from
`.claude/agents/`, ownership zones, and a context pack. `ls .claude/teams/*.yaml` is your org
chart.

## License

MIT — see [LICENSE](LICENSE). Developed independently on personal time and equipment.
