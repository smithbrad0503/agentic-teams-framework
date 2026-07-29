# Roadmap — post-v0.1.0

**Status:** drafted 2026-07-26, from two evidence passes over the v0.1.0 asset.
**Evidence base:** 58 real team-runs on a private production project (2026-07-18 → 07-25),
the runner source, and the published v0.1.0 plugin.

This roadmap is derived from measurement, not from a wish list. Every item below traces to
either an observed run failure or a question a buyer asks that the asset cannot currently
answer. Items with neither are parked at the bottom.

---

## What the evidence actually says

**The engine works better than the README claims.**

| Measure | Actual |
|---|---|
| Team-runs recorded | 58 |
| Reached `pr-ready` | 52 (89.7%) |
| Distinct PRs opened | 56 |
| PRs merged | 54 |
| **PRs closed unmerged** | **0** |
| Runs clean on gate round 1 | 28 of 56 (50%) |
| Median tokens per run | ~459k |
| Median diff (add+del) | 930 lines |

Zero abandoned PRs across 58 runs is the strongest single fact the framework has, and it is
not stated anywhere public. The README currently claims "~30 merged PRs and 13+ team-runs" —
the one public claim is stale and understates reality.

**The distribution mechanism has never been executed.** `/org-init` — the thing v0.1.0
actually ships — has zero real-project runs. Both installed orgs were hand-installed; neither
carries a provenance header. The design spec set a dogfood gate on exactly this and the repo
went public without meeting it.

**All six non-success runs trace to framework defects.** None was caused by a vague brief or a
genuinely broken build. That is good news — the failures are fixable in code, not inherent —
but it means the 10.3% non-PR rate is a bug rate, not a floor.

---

## Three themes, not twenty tickets

The nine runner defects found in telemetry collapse into three root causes. Fixing the themes
fixes the tickets.

### Theme 1 — The gate loop cannot converge, and cannot verify its own last action

Explains 5 of the 6 non-success runs. Three defects, one mechanism.

| ID | Defect | Root cause |
|---|---|---|
| D1 | Review gate is stateless across rounds — each round is a fresh unbounded audit producing findings disjoint from the last, so runs cannot converge | `history` is declared at `team-run.js:422`, pushed to at `:448`/`:473`, serialized at `:502` — and **never interpolated into any prompt**. Round 3's reviewer has no idea what round 1 asked for. Verified by grep. |
| D2 | The final round's fix executes but is never verified; the reported terminal status is stale relative to branch HEAD | Asymmetric guard. The CI path breaks before spending an unverifiable fix (`:474` `if (ciAttempts >= 3) break`). The review path has no equivalent — `:444-459` runs `revise#3` and then falls out of a loop condition already false. Cost: 78k tokens across 4 runs, plus one run reported `review-stalemate` that a human then merged unchanged. |
| D4 | One round budget serves two independent gates; a mechanical CI-only fix forces a full re-review, which re-opens the unbounded audit from D1 | Single `while` loop at `:427-492`; both failure branches `continue` back to review at `:429`. There is no path that returns to the CI gate directly after a CI fix. 11 of 58 runs (19%) sit at the round ceiling — `MAX_ROUNDS` is a routinely-binding constraint, not a safety net. |

**Fix as one change:** inject prior-round history into the review prompt with an explicit
"verify these first; new non-regression findings are nits, not blockers" rule; guard the review
path's final fix the same way CI is guarded, or spend the last round on a verify-only pass so
the terminal status reflects HEAD; give each gate its own budget and re-enter at the gate that
failed.

**Why first:** it is the difference between a 89.7% and a plausible ~97% run success rate, and
every non-success run costs real triage time that a paid engagement has to absorb.

### Theme 2 — The framework cannot measure itself

This is simultaneously the top *engineering* gap and the top *sales* gap. Same fix.

| ID | Defect | Root cause |
|---|---|---|
| D6 | The event stream collapses `blocked`, `review-stalemate`, `needs-human`, and `ill-specified` into one event type | `:506` is a two-way branch over a five-value status space; `:146` hardcodes `type: 'blocked'`. Every question this roadmap answers is unanswerable from `events.jsonl`. |
| D10 | `board.json` never reconciles with real PR state — it showed 21 `done` while GitHub showed 54 of those PRs merged | Nothing reads PR state back into the board after a run ends. `/team status` renders a stale picture, which is how the public README number drifted low. |
| — | `/model-eval` does not exist | Described in `docs/design.md:131-139` and referenced twice in runner comments. 58 runs of clean telemetry with no reader. |
| — | No cost model | Telemetry records tokens only — no input/output split, no cache accounting, no price table. Cost per run is currently a shrug across a 5× range. |
| ~~D8b~~ | ~~The `report:state` stage's own token cost is invisible~~ | **Fixed in v0.2.0.** Structurally unfixable in-file (the record is serialized before the writer runs; patching it afterwards is itself an unrecorded stage), so it was made *recoverable*: the record carries `tokensBeforeReport`, and the workflow's return value lists the stage. |
| ~~D8a~~ | ~~`size` is accepted and recorded but changes no behavior~~ | **Closed in v0.2.0** by removing the promise, not the parameter: `/team`'s usage, the setup guide, and the runner's args contract now say `size` is a telemetry label. Gate budgets are the tunable (`maxReviewRounds` / `maxCiAttempts` / `maxGateRounds`). |
| D8c | Gate budgets have no config surface | **Still open.** `maxRounds` / `maxReviewRounds` / `maxCiAttempts` / `maxGateRounds` are settable per dispatch, but nothing reads a per-team default out of the team yaml. |

**Fix as one change:** a metrics script over `state/runs/*.json` + `gh pr list` that produces
run success rate, first-pass rate, merge rate, rounds distribution, token and dollar cost per
merged PR. Correct the event-type branch, reconcile the board against PR state, and record a
`RUNNER_VERSION` in telemetry so a deployed copy can report what it is.

**Why second:** it closes four of the ten productization gaps at once and turns "I'd have to go
compute it" into a number. Roughly a day of work sitting on top of a week of data.

### Theme 3 — Infrastructure failures are misclassified as code or brief failures — **fixed in v0.2.0**

| ID | Defect | Root cause | Fix as shipped |
|---|---|---|---|
| D5 | A model-level stage failure is retried on the identical model with no fallback and no error captured | `withRetry` re-invoked with the same `opts`. The routing fallback fired only when a *stage class key* was missing, never when a named model was unreachable — the routing file even carried a comment describing a fallback no code implemented. `call()` recorded an error string only on a thrown exception, so a null return left diagnostically empty telemetry. Two runs died at decompose at the same timestamp; the same brief succeeded 29 minutes later on a different model. One of those tickets was never re-dispatched and is silently still lost. | The one retry escalates to a real `fallback: {model, effort}` route — new top-level key in `model-routing.yaml`, overridable per team, validated by `validate_org.py`, with a conservative built-in default — and logs the switch. Every failure records a reason, including null returns, and `blocked()` quotes it. |
| D3 | A CI runner-capacity outage is treated as a code failure — the framework dispatched a fixer against a non-existent defect, burned a round and 40k tokens, and pushed the run toward the stalemate it then reached | `CI_SCHEMA` had no infra flag. The CI agent correctly identified the outage in free-text `reason`; the code never read it. | `CI_SCHEMA`'s failing item gained an optional `infra: boolean` (optional so an unfilled flag reads false and still routes to the fixer), the CI prompt instructs it, and a red whose checks are *all* infra takes a `ci-rerun` path that refunds the gate round. `maxCiInfraReruns` (default 2) bounds it; the count rides in telemetry as `ciInfraReruns`. |

**Not in scope, deliberately:** auto-re-dispatching a blocked run. Making the failure
diagnosable and the retry meaningful is a code change; deciding to spend tokens again on a run
a human never saw is a policy call.

**Why third:** lower frequency than Theme 1, but each occurrence loses a whole ticket silently,
which is the worst failure shape for a paid engagement.

---

## Sequencing

### v0.2.0 — Convergence and honesty *(the next release)*

1. Theme 1 in full — history injection, symmetric final-round guard, decoupled gate budgets.
2. Theme 2's metrics script + event-type fix + board reconciliation + `RUNNER_VERSION`.
3. Update the README with the real numbers, including **0 PRs closed unmerged**.
4. Add a GitHub Actions workflow that runs the existing pytest suite. Two docs currently assert
   "CI enforces" the context-pack cap and there is no `.github/` directory at all. Under an hour,
   and it removes a visible credibility hole on a project whose entire pitch is rigor.
5. Theme 3 in full — retry escalation to a configured `fallback` route, a reason on every stage
   failure, and the bounded infra re-run path (pulled forward from third place: each occurrence
   loses a whole ticket silently). Plus D8a/D8b and D9, which are one-line-each companions.

A v0.2.0 tag is also a prerequisite for testing `/org-update` at all — its three-way baseline
recovery does `git show v<version>:<source>`, and only `v0.1.0` exists, so that path has never
executed even once.

### Shipped since this roadmap was written

- **v0.2.0** — Theme 1 (converging gate loop, confirm-only verification, per-gate budgets),
  Theme 2 (`run_metrics.py`, event types, `RUNNER_VERSION`, board reconciliation), Theme 3
  (fallback route on retry, a reason on every failure, bounded infra re-runs), plus D8a/D8b/D9.
- **v0.3.0** — four recipes harvested from a sibling project's production workflow library
  (`triage`, `batch-author`, `release-gate`, `consistency-sweep`), and one shared
  degraded-outcome contract: every recipe returns a `verdict`, with `INCOMPLETE` reserved for
  agent death. `health-check` stopped conflating a check that failed with one that never ran.
- **v0.4.0** — `/recipe-new` authoring skill, agent-wiring validation in `validate_org.py`, and
  a manifest-vs-tag version guard.
- **v0.5.0** — three recipes harvested from a second production project's workflow library
  (`first-run`, `dependency-probe`, `state-reconcile`), built by three independent authors
  following `/recipe-new` — its first real use. Their converged deviation logs fixed the skill.
  Also fixed an outer-layer silent drop in `audit` and `consistency-sweep`: `.filter(Boolean)`
  over `pipeline` results deleted an entire checklist item or surface whose stage threw, so an
  audit could report clean on a checklist it never finished. Skill and plugin authoring were deliberately NOT built:
  `skill-creator`, `superpowers:writing-skills` and `plugin-dev` already cover them upstream.

> **Note on `v0.3.0`.** The original tag was deleted. It pointed at a tree whose `plugin.json`
> still said `0.2.0`, so anything materialized from it would have stamped the wrong provenance
> and `/org-update` would have diffed against a version that never shipped. The repo had no
> consumers at the time. The guard added in v0.4.0 compares the manifest against the highest
> release tag so this cannot recur.

### v0.5.0 — Prove the distribution mechanism

The pilot: run `/org-init` literally, on a real repo that is not the one whose packs were
hand-tuned over 58 runs, and do not rescue the wizard. Instrument what has never been measured:
human review minutes per PR, dollar cost per merged PR, rework rate at 14 days. Then run
`/org-update` from v0.2.0 → v0.4.0 against that org.

The single highest-signal free measurement in the pilot: diff the wizard's output against the
hand-built org it replaces. Wherever an experienced human wrote something the wizard didn't,
that is the `/org-init` backlog.

Ship alongside: a failure-triage runbook per terminal state, written from the six real failures
already sitting in telemetry, and a `software-engineer` generalist identity to close the roster
gap that currently confines the framework to web-service-shaped repos.

### v0.6.0 — Sustain

- **Librarian**: flag context packs whose staleness date predates recent merges in their zones.
  Flag-only, never auto-rewrite. The docs warn that a stale pack "silently misleads every agent"
  and nothing currently detects one.
- **D7 — cross-zone arbitration**: `outOfZoneNeeds` is promised in the guardrails injected into
  every mutating agent and defined in `BUILD_SCHEMA`, but never read anywhere in the runner. Two
  concurrent runs collided on the same files and it was caught by a reviewer three rounds in, by
  luck. Aggregate the field, surface it in state, and add a pre-dispatch collision check.
- ~~**D9 — the `ill-specified` escape hatch has never fired in 58 runs.**~~ **Made reachable in
  v0.2.0.** `PLAN_SCHEMA`'s hard requirement is now `feasible` alone, so
  `{feasible:false, questions:[...]}` is a valid report; the conditional shape (`feasible=true`
  ⇒ packages + testPlan) moved into the decompose prompt, and the runner blocks cleanly on a
  `feasible=true` plan that arrives without packages instead of crashing on `.length`. Whether
  0/58 was caused by the schema or by 58 adequately-specified briefs is still unknown — no
  decompose report from those runs was retained. What changed is that the schema can no longer
  be the reason.
- **Crash resume** (`resumeFromRunId`) — currently documented as planned, implemented nowhere.

### Parked — real v2, once the above is true

Deferred deliberately at v1 and still correctly deferred: dynamic workflow *generation* from a
description; a structured/queryable knowledge base replacing file-based org memory;
industry-specific agent packs; cross-project portfolio memory; paid tiers and licensing.

None of these should start before the pilot clears. They add surface area to a mechanism that
has not yet been proven to work once.

---

## The propagation problem, called out separately

The production project is running a **486-line fork** of the current 535-line runner — behind by
the entire org-memory feature, with project specifics hardcoded into the runner body that the
current version pushes into config. It arrived by hand-copy, its `.claude/` is untracked, and
the runner file carries no version string, so a deployed copy cannot report what it is and
telemetry cannot say which runner produced a run.

Every defect in this document reproduces in both copies, so none is a fork artifact. But this is
the concrete case for `/org-update` existing — and the concrete demonstration that shipping an
update mechanism is not the same as anyone being on it.

**One-line fix with outsized value:** a `RUNNER_VERSION` const recorded in telemetry. It makes
every future defect-mining pass tractable.

---

## What is deliberately not on this list

- **Loosening the review gate.** In the two runs where the gate held a PR back for three rounds,
  every finding was factually correct — including a silent wrong-data path and a persistence bug
  verified numerically. The gate did its job; the *loop bounding it* failed. Fix the loop, not
  the gate.
- **Per-ticket agent-quality tuning.** No run in the dataset failed because an agent wrote bad
  code. The failures are all in orchestration.
