# Agentic Teams Framework — Design

**Status:** Battle-tested. Extracted into a portable package after ~30 merged PRs and
13+ team-runs on a production codebase.

---

## 1. Problem & Goals

Agentic development on a real codebase runs into four recurring pains:

1. **Throughput** — work serializes through one session; independent frontend / backend /
   infra tasks should run simultaneously in isolated worktrees.
2. **Manual orchestration** — which agents fire, in what order, with what gates is
   hand-managed per task.
3. **Context loss** — every spawned agent starts cold; findings and lessons die when a
   subagent exits.
4. **Token burn** — agents repeatedly re-explore the same codebase; no discipline on what
   each agent loads or which model/effort tier each stage uses.

**Goal:** a team-based orchestration framework where one cockpit session dispatches named
teams into isolated worktrees; teams run a deterministic gated pipeline with model-tiered
stages, share context through disk state, accumulate memory across runs, and stop at human
approval points. The framework covers the full org (delivery + advisory teams), not just
engineering.

## 2. Locked decisions

| Decision | Choice |
|---|---|
| Operating model | One cockpit session dispatches background team workflows; cockpit never implements |
| Work shape | Both independent tickets and split features (contract-first, parallel teams) |
| Merge approval | Feature-level merge train: one briefing, one approval, dependency-ordered merges. **Merges always require explicit human approval.** |
| Model strategy | Deterministic per-stage model routing; **start strong, demote on evidence** |
| Architecture | Workflow-native (deterministic runner scripts) with team-lead agents doing judgment work inside runs |
| Org scope | Full org: delivery teams (PR output) + advisory teams (document output), one runner with two output modes |
| Cleanup | In scope: automatic post-merge cleanup + orphan sweep |

## 3. Architecture overview

```
Cockpit (one session — dispatcher, not implementer)
│
├── dispatches ──► team-run.js (backend)  ── worktree ─► gated PR
│                  team-run.js (frontend) ── worktree ─► gated PR
│                  team-run.js (platform) ── worktree ─► gated PR
│
└── shared state on disk (.claude/teams/):
      <team>.yaml           team defs: roster, gates, ownership zones, routing overrides
      model-routing.yaml    global stage-class → {model, effort} defaults
      context-packs/*.md    curated ~1-2k-token briefings per team
      state/events.jsonl    cross-team event feed
      state/board.json      active runs: id, team, ticket, worktree, status
      state/runs/*.json     per-run telemetry (stage × model × tokens × gate outcomes)
      memory/<team>.md      per-team lessons, appended by runs, pruned by a librarian pass
```

Key properties:

- **Thin cockpit.** Scouts, dispatches, relays briefings, takes approvals. Never implements.
- **A team is a definition + a memory, not a standing process.** Runs are ephemeral
  Workflow runs; continuity lives in yaml + context pack + lessons file.
- **Deterministic skeleton, intelligent interior.** Phases, worktrees, gates, and the merge
  train are code. Stage 1 of every run is a team-lead agent (strong model) doing decomposition.
- **File-ownership zones** per team enable collision detection at dispatch time; overlapping
  zones force sequencing or an explicit handoff event.

## 4. The org: team definitions

### Delivery teams (output: gated PRs)

| Team | Roster (example) | Ownership zones |
|---|---|---|
| frontend | frontend-expert (lead), ux-designer, qa-tester | `frontend/` |
| backend | backend-expert (lead), api-expert, qa-tester | `src/api/`, `src/tasks/`, `src/services/` |
| platform | cloud-infra-expert (lead), database-expert, sre | `infra/`, migrations, IaC stacks |

### Advisory teams (output: reviewed documents)

| Team | Roster (example) | Deliverable |
|---|---|---|
| product | product-manager (lead), ux-designer, analytics-expert | PRDs, roadmaps, specs |
| growth | marketing-expert (lead), copywriter | Content, campaigns — **legal-expert is a hard gate** on claims |
| business-ops | finops-expert (lead), legal-expert | Financial models, cost reviews, compliance docs |

### Roles, not teams

- **Coordination:** orchestrator, tech-lead.
- **Gates / escalation (on call to every team):** code-reviewer, debug-expert.
- **Shared services:** github-expert, docs-author (invoked as a stage, not a team member),
  plus optional notion-expert / slack-expert where an MCP connection exists.

`ls .claude/teams/*.yaml` **is** the org chart — the org is reified as executable team
definitions and cannot go stale.

### Team definition (see `.claude/teams/TEMPLATE.yaml`)

```yaml
name: backend
type: delivery            # delivery | advisory
output: pr                # pr | document
mission: Server-side routing, task wiring, API-contract fidelity
roster:
  lead: backend-expert
  specialists: [api-expert]
  test: qa-tester
ownership: [src/api/, src/tasks/]
context_pack: context-packs/backend.md
gates: [code-review, ci-green]
budget_defaults: { small: 80000, medium: 200000, large: 500000 }
routing:                  # overrides global defaults only where earned
  implement: { model: mid, effort: medium }
```

## 5. Model routing & the evaluation loop

Global defaults live in `model-routing.yaml`, keyed by **stage class** (per-team overrides
allowed). Model names are placeholders — map `strong` / `mid` / `cheap` to your org's models.

| Stage class | Initial tier | Effort | Rationale |
|---|---|---|---|
| decompose / design / contract | strong | high | Wrong plan wastes every downstream token |
| implement | strong → demote to mid | medium | Start strong, earn the demotion |
| write-tests | mid | medium | Well-specified once design exists |
| docs-author | mid | medium | Structured, source-grounded writing |
| mechanical (formatting, state writes, doc sync) | cheap | low | Only after evidence |
| review / verify / compliance gate | strong | high | **Never demote the gatekeeper** |
| revision-fix | mid | medium | Findings are specific by this point |
| librarian (pack refresh) | cheap | low | Mechanical summarization with pointers |

`model-routing.yaml` also carries a top-level `fallback: {model, effort}` — not a stage class,
but the route a failed stage's single retry escalates to. Teams may override it under `routing:`
like any stage class.

**Evaluation loop** (measure, don't assert):

- Every run appends per-stage telemetry to `state/runs/`: model used, tokens, revision
  rounds, review findings, CI outcome.
- A periodic aggregation (`/model-eval`) recommends per stage-class × team: keep / demote /
  promote-back.
- **Demotion rule:** requires ≥10 clean runs at the current tier (median ≤1 revision round,
  zero gate escapes). **Promotion back is immediate** on quality-regression evidence.
- A human approves routing changes; the review/verify class is never demoted.

**What exists today:** `scripts/run_metrics.py` is the reader for that telemetry. It walks a
project's `.claude/teams/state/` and prints the evidence table the loop needs — run census by
terminal status, runs-to-PR rate, first-pass gate rate, rounds distribution, token spend by
stage class, and **per-(model, effort) invocation counts, success rates, and token totals**,
which is the demotion loop's input. Dollar cost is reported as a *range* over plausible
input/output mixes, because telemetry records only a per-stage total with no input/output
split; the price table is an editable constant (`--prices` overrides it). One stage is missing
from every persisted record by construction: the state-writer's own cost, because the record
has to be serialized before the writer runs. It is recoverable rather than lost — the record
carries `tokensBeforeReport`, the run's total spend at serialization time.

```
python3 scripts/run_metrics.py --project-root /path/to/project       # text
python3 scripts/run_metrics.py --project-root /path/to/project --json
python3 scripts/run_metrics.py --project-root . --gh --reconcile     # needs the gh CLI
```

`--gh` cross-references PR merge state (opened / merged / open / closed-unmerged, merge rate,
cost per merged PR); it is off by default so the script never requires network, and degrades
to the offline metrics if `gh` is missing or unauthenticated. `--reconcile` reports — and
never writes — `board.json` entries that disagree with the run records or with real PR state,
because `board.json` is a human-curated surface. The recommendation step (keep / demote /
promote-back) is still a human reading this table; there is no `/model-eval` command yet.

## 6. Context packs, shared state & memory

### Context packs (the primary token lever)

Curated ~1–2k-token briefings (hard cap ~3k / 12k chars, enforced in CI) injected into every
agent prompt in a team's runs, replacing cold exploration. Rules:

- **Pointers over content** — where to Read, never pasted code.
- **Trip-wires over tutorials** — the lessons that burned you (a naming convention, a
  migration-proof requirement, a gitignore trap), not generic guidance the model already knows.
- **Staleness header + automated refresh** — a librarian step refreshes packs after merges
  touching the team's zones. A stale pack is worse than no pack.

### Shared state during runs

- `state/events.jsonl` — append-only cross-team feed (`contract_updated`, `pr_opened`,
  `zone_conflict`, `blocked_on`, plus the terminal statuses `blocked`, `review-stalemate`,
  `needs-human`, `ill-specified`, and the advisory `document-ready` / `critique-stalemate` —
  a run's end event carries its actual outcome, never a
  collapsed one). Runners append; team-runs read at **phase boundaries only** (no polling).
- `state/board.json` — active-runs registry; powers `/team status` with zero agent spawns.

### Memory hierarchy (one owner per layer, no duplication)

| Layer | Lives in | Owner |
|---|---|---|
| Operator preferences / strategy | cockpit auto-memory | Cockpit |
| Team lessons | `teams/memory/<team>.md` | Appended by runs, pruned by librarian |
| Repo conventions | CLAUDE.md + context packs | Librarian refresh |
| ADRs / incidents | external knowledge base (source of truth) | Human + cockpit |

Run telemetry is data, not memory — pruned after aggregation.

### Org memory (the cross-team layer)

`.claude/org-memory/` holds three capped files — `decisions.md`, `architecture.md`,
`lessons.md` (≤8k chars each, same philosophy as packs: small, curated, high-signal).
The dispatcher concatenates them into `config.orgMemory`; the runner injects the result
into the **decompose** and **review** prompts only (the stages where cross-team context
changes outcomes — mutating stages stay lean). Any stage may report `orgLessons`
(cross-team, durable; rare); the Report stage appends them as `- [ ] (<runId>) …`
candidate lines under `## Candidates (pending curation)` in `lessons.md`, uncommitted.
Humans curate candidates up into the files; runs never write above that heading. One
owner per layer still holds: team memory (holding area) → context pack (team canon) →
org memory (cross-team canon).

## 7. The runner

### `team-run.js` — one team, one task, one worktree → gated deliverable

```
0. setup          resolve team config (skipped when /team dispatch injects it)
1. decompose      lead agent (strong): breakdown, file plan, risk flags
                  → structured output; aborts if task is ill-specified (cheap failure)
2. implement      specialists on the run branch (worktree-isolated), sequential on one branch
3. test           test role writes/extends tests (regression pin for high-severity bugs)
4. docs           docs-author updates affected repo docs (ships IN the PR)
5. review gate    code-reviewer (strong/high): findings → revision rounds (own budget, max 3);
                  each round is handed the prior rounds' findings and re-checks them first
6. CI gate        push branch, open PR, `gh pr checks --watch` — full CI, never local slices;
                  own budget (max 3 attempts), re-entered directly after a review-neutral fix
6b. confirm pass  if a gate bounded out right after a fix, ONE confirm-only re-check of just
                  those items, so the terminal status describes branch HEAD (`verifiedAtHead`)
7. report         append telemetry + lessons; emit the terminal status as the event type;
                  STOP (never merges)
```

### Document mode (advisory teams, `output: document`)

A second path in the same runner, selected by the team yaml's `output` field. It keeps the
half of the delivery skeleton that carries the safety — an adversarial gate run by a
non-author, bounded — and drops the half that assumes a PR:

```
0. setup          identical (the dispatcher injects `output` with the rest of the config)
1. advise         team lead (strong): writes the DOCUMENT into the team's ownership zones
                  → structured output: recommendation, document path, open questions,
                    what needs human approval. Forbidden from editing application source.
2. critique gate  a NON-AUTHOR critic (roster.test, else code-reviewer) runs one pass per
                  NAMED failure lens — ungrounded claim, stale grounding, scope expansion,
                  hidden cost/risk, undecidable advice. Each must-fix finding is then
                  attacked by TWO independent refuters; it dies only if every live refuter
                  refutes it. A finding whose refuters all died STANDS, marked unverified.
3. revise         lead addresses the standing findings; loop back to 2 (own bounded budget,
                  `maxCritiqueRounds`). A revision is only dispatched when another critique
                  round will read it, so the reported verdict always describes the document
                  on disk — no confirm-only pass is needed on this path.
4. report         verdict + telemetry + board/event/memory writes; STOP
```

`verdict` follows the recipe contract: **`APPROVED`**, **`REVISE`** (findings still standing
when the budget ran out), or **`INCOMPLETE`** — reserved, as everywhere else in this
framework, for *an agent died, so this is not a complete judgement*. INCOMPLETE **outranks**
a clean result: a gate that lost a lens, lost both of a finding's refuters, or lost a
revision cannot certify a document, and the run reports `needs-human` rather than a
deliverable. Terminal statuses are `document-ready` / `critique-stalemate` / `needs-human`,
recorded in the same telemetry shape as a delivery run with `branch` and `pr` empty.

**The path creates no branch, opens no PR, and never touches CI** — which is why an advisory
team declares `gates: [critique]` and not `ci-green`: there is no PR for CI to watch, so
`ci-green` would name a check nothing could ever perform (`scripts/validate_org.py` enforces
the split). Nothing publishes externally without human approval.

### Error-handling doctrine (every failure has a named owner and a stopping point)

| Failure | Handling |
|---|---|
| Agent dies / returns null | One retry with failure context; second failure → stage `blocked`, event emitted, reported. Never silently skips. |
| Agent throws (e.g. structured-output retry cap) | The `call()` wrapper catches the throw and returns null, so the retry/blocked policy governs — a throw never kills the run. |
| Review loop exceeds 3 rounds | Stop, don't grind. The last round's fix gets one confirm-only re-check of the outstanding items (never a fresh audit); if they are still unresolved, report "review stalemate" + those findings. Usually a decompose problem. |
| CI red after revisions | The specialist fixes CI first; a second red gets debug-expert one root-cause pass; a third red → blocked + report. CI has its own attempt budget, so a mechanical fix never spends a review round. No "merge anyway" path exists. |
| A CI fix that edits source or existing test assertions | The review gate re-runs before the run can reach `pr-ready` — the fixer reports `touchedSource`, and anything short of an explicit `false` routes back through review. A confirm-only review can never promote a run whose CI was not separately verified green. |
| An advisory gate stage dies (a critique lens, both refuters on a finding, a revision) | The loss is recorded, never collapsed into "found nothing". The verdict latches to `INCOMPLETE` and the run reports `needs-human` — a document whose gate lost a stage is not a reviewed document. A finding nobody could refute stands rather than being dropped. |
| Zone conflict mid-run | `zone_conflict` event; the junior claim pauses; the cockpit arbitrates. |
| Crashed / interrupted run | State is persisted on every early exit; a `resumeFromRunId` resume from the last completed stage is the planned enhancement. |
| Budget exhausted | Runs check budget at phase boundaries; stop cleanly at the last completed stage. Partial gated work, never half-implemented pushes. |

### Report-format discipline

Every string field in a stage's final structured report must be **short and single-line
(≤300 chars, no newlines, no backticks)**. Long multiline strings break the report parser and
fail the whole stage. Detail goes in the PR body and commit messages, never in the report.

## 8. Merge-train discipline

Split features fan out to parallel team-runs, each producing an independent gated PR. The
merges are then run as a dependency-ordered **merge train**: one briefing lists the PRs,
review summaries, and merge order; a human approves once; merges apply in order with CI
re-verified between each; the train **halts immediately on any red** and reports the broken
merge plus the remaining queue. It never continues past red, and there is no path that merges
without explicit human approval.

## 9. Cleanup lifecycle

- **Dispatch-side:** always sync the default branch to origin before creating worktrees
  (never branch from a stale base).
- **Post-merge (automatic):** remove feature worktrees, delete merged branches (local +
  remote), fast-forward the local default branch, clear board entries, archive events.
  Squash-merges are invisible to `git branch --merged`, so cleanup keys off PR state
  (`gh pr view --json state`), not the merged-branch heuristic.
- **Orphan sweep** (in `/team status`): worktrees/branches with no live run and no open PR
  are **flagged**, not auto-deleted (an orphan may be a resumable crashed run).
- **Never touched by cleanup:** unmerged branches with open PRs; anything with uncommitted
  changes. Those surface to a human first.

## 10. Testing strategy

- **Runner logic:** the workflow script is deterministic JS — dry-run mode (mock `agent()`
  returns via `fixtures` args) validates phase ordering and gate enforcement without spawning
  agents.
- **State & definitions:** JSON-schema / yaml-schema checks on team defs, context packs, and
  board/events entries run in CI, so a malformed writer fails fast.
- **Regression:** any framework bug that reaches a PR gets a pinned regression test.

## 11. Battle-tested lessons baked in

These were paid for in debugging and are encoded directly in the runner and guardrails:

- **Args may arrive as a JSON string** — normalize before validating.
- **`agent()` can throw** (structured-output retry cap) — `call()` wraps it in try/catch → null.
- **Report strings must be single-line ≤300 chars** — multiline breaks the parser.
- **Persist board/events on every early exit** — a blocked/ill-specified run must still update state.
- **Squash merges are invisible to `git branch --merged`** — use PR state for cleanup.
- **Refetch before fire** — never dispatch from a stale base; sync origin first.
- **Worktree CWD drift** — shells can drift into a worktree; use absolute paths and
  `git rev-parse --show-toplevel` for main-checkout writes.
- **Conservative routing fallback** — a missing stage-class routing entry falls back to the
  strong tier, never silently to the cheapest.
- **A retry must change something** — a stage that returns nothing may have failed at the model
  level, so its one retry escalates to the routing file's `fallback` route instead of
  re-invoking the model that just failed. Every stage failure records a reason, including null
  returns; `ok:false` with no error text is what makes an incident unreconstructable.
- **Infrastructure is not a defect** — a CI red whose failing checks are all flagged `infra`
  (runner capacity, queue, quota, provider outage) is re-run rather than handed to a code
  fixer, and the re-run does not consume a gate round. Bounded by `maxCiInfraReruns`.
