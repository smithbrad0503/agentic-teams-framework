# Agentic Teams Framework

A deterministic, config-driven orchestration framework for Claude Code. From one cockpit
session you dispatch **named teams** at tickets; each team runs a **gated pipeline** in an
isolated git worktree and returns a **code-reviewed, CI-green pull request** — and stops.
**It never merges.** Merge approval is always a human decision.

This is an extraction of a framework that proved itself over ~30 merged PRs and 13+
team-runs on a production codebase. The machinery is generic; everything project-specific
lives in config you write (team yamls + context packs).

## What it is

- **A team is a definition + a memory, not a standing process.** `ls .claude/teams/*.yaml`
  is your org chart. Runs are ephemeral; continuity lives in yaml + context pack + a lessons
  file that grows across runs.
- **One deterministic runner, `team-run.js`**, drives every run through the same skeleton:
  `decompose → implement → test → docs → review gate → CI gate → report`. The phases,
  worktrees, and gates are code; the judgment inside each stage is an agent.
- **Per-stage model routing** (`model-routing.yaml`): the strongest model plans and reviews,
  a mid model implements and tests, a cheap model does mechanical work. Philosophy:
  **start strong, demote only on evidence; never demote the review gate.**
- **Context packs** are the token lever — curated ~1–2k-token briefings (pointers, not code;
  trip-wires, not tutorials) injected into every agent so they don't re-explore cold.
- **Full org, two output modes:** delivery teams emit gated PRs; advisory teams (product,
  growth, business-ops) emit reviewed documents through a compliance gate.

## 10-minute quickstart

1. **Copy the tree in.** Drop this package's `.claude/` into your project's `.claude/`
   (merge if one exists). Add to your `.gitignore`:
   ```
   .claude/teams/state/*
   !.claude/teams/state/.gitkeep
   ```
2. **Map the models.** In `.claude/teams/model-routing.yaml`, replace the placeholder tier
   names (`strong` / `mid` / `cheap`) with the model identifiers your setup exposes. Keep the
   shape: decompose + review on the strongest tier.
3. **Define a team.** Copy `.claude/teams/TEMPLATE.yaml` → `backend.yaml`; set the roster
   (agent names from `.claude/agents/`), the `ownership` file zones, and the `context_pack`.
4. **Write the pack.** Copy `.claude/teams/context-packs/TEMPLATE.md` → `context-packs/backend.md`:
   where things live (`## Map`), the landmines (`## Trip-wires`), what's in flight
   (`## Current state`). Hard cap ~12k chars.
5. **Dispatch.** From your cockpit session:
   ```
   /team dispatch backend TICKET-123 "Add a /v2/items endpoint with tier-based access" medium
   ```
   The run works in the background and returns a gated PR. Watch it with `/team status`.
   **Review and merge the PR yourself** — the runner never will.

Full walkthrough: [`docs/setup-guide.md`](docs/setup-guide.md). Architecture & rationale:
[`docs/design.md`](docs/design.md).

## Architecture at a glance

```
Cockpit (one session — dispatcher, not implementer)
│  /team dispatch <team> <ticket> "<brief>"
▼
team-run.js  ── isolated worktree ──►  decompose → implement → test → docs
                                        → review gate → CI gate → report  ──►  gated PR (STOP)
│
└── shared state on disk (.claude/teams/):
      <team>.yaml          roster · ownership zones · routing overrides
      model-routing.yaml   global stage-class → {model, effort}
      context-packs/*.md    per-team briefings (the token lever)
      memory/<team>.md      lessons, appended by runs
      state/                board.json · events.jsonl · runs/*.json  (gitignored)
```

## Layout

```
.claude/
  workflows/team-run.js         the runner (config-driven; see its header for the contract)
  commands/team.md              /team dispatch | status
  teams/
    model-routing.yaml          global per-stage model/effort defaults (placeholders)
    TEMPLATE.yaml               annotated team-definition template
    context-packs/TEMPLATE.md   annotated context-pack template
    memory/TEMPLATE.md          annotated team-lessons template
    state/.gitkeep              runtime board/events/telemetry live here (gitignored)
  agents/                       the full agent org (sanitized, generic)
    AGENTS.md                   registry: roster, tiers, when to invoke
    optional/                   agents that need an MCP connection (notion, slack)
docs/
  design.md                     full design + the battle-tested lessons baked in
  setup-guide.md                step-by-step adoption
tests/                          schema/hygiene tests for team defs, packs, state
dist/
  dev-team-package/             self-contained software-developer-team subset (+ .zip)
```

## The core invariant

The runner **opens a PR and stops.** It never merges, never pushes to the default branch, and
never runs stateful/outward operations (deploys, production DB writes, queue drains) — those
are documented as ops steps in the PR body. Every path that ends a run leaves valid state
behind and surfaces a clear status. Human approval is the only way work lands.

## Battle-tested lessons baked in

Encoded directly in the runner and guardrails (each was paid for in debugging):

- Args may arrive as a JSON string — the runner normalizes before validating.
- `agent()` can throw (structured-output retry cap) — `call()` wraps it in try/catch → null so
  the retry/blocked policy governs instead of the run dying.
- Report strings must be single-line ≤300 chars — long multiline strings break the parser.
- Board/events are persisted on **every** early exit (blocked / ill-specified), not just success.
- Squash merges are invisible to `git branch --merged` — cleanup keys off PR state.
- Refetch before fire — never dispatch from a stale base.
- Worktree CWD drift — use absolute paths; do main-checkout writes via `git rev-parse --show-toplevel`.
- Missing routing entries fall back to the strong tier, never silently to the cheapest.

## Need just a dev team?

`dist/dev-team-package/` is a self-contained subset with only the software-developer roster,
a ready-to-use `dev` team, and a 15-minute quickstart written for a corporate setting. It also
ships zipped as `dist/dev-team-package.zip`.

## License

MIT — see [LICENSE](LICENSE). Developed independently on personal time and equipment.
