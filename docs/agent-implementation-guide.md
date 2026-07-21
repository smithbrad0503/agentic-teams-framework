# Agent Implementation Guide

> **Audience: an AI coding agent** (Claude Code or equivalent) asked to install and adapt
> this package for a repository it has access to. A human should point you at this file with
> a prompt like: *"Read docs/AGENT-IMPLEMENTATION-GUIDE.md from the dev-team package and
> implement it for this repo."* Humans can read it too, but every step is written to be
> executable by an agent.

You are installing a team-dispatch framework: a deterministic runner (`team-run.js`) that
drives `decompose → implement → test → docs → review gate → CI gate → report` and ends every
run at an **open pull request — never a merge**. Your job is to adapt its config to THIS
repository, verify it with a dry run, and hand the human a working first dispatch.

Execute the phases in order. Each phase ends with a checkpoint; do not proceed past a failed
checkpoint. Phases 2 and 3 contain decisions **you must ask the human** — do not guess them.

---

## Phase 0 — Discovery (read-only)

Build a picture of the repo before touching anything. Record answers to all of these:

1. **Stack + layout:** primary language(s); where application code lives (top 2–4 source
   directories); where tests live; monorepo or single-package?
2. **Commands:** how to install deps, run the test suite, run the linter/formatter, run the
   type-checker. Look in `package.json` scripts, `Makefile`, `pyproject.toml`, CI config,
   `CONTRIBUTING.md`. Record exact commands — the context pack will carry them.
3. **CI:** which system (GitHub Actions / GitLab CI / Jenkins / other); which checks gate a
   PR; typical time-to-green. The runner's CI gate polls PR checks via `gh` — if the repo
   host is not GitHub, flag this to the human now (the runner's PR + CI steps assume `gh`).
4. **Branch rules:** default branch name; branch protections; naming conventions for
   branches and commit messages (conventional commits?). The runner creates branches named
   `<ticket>-<team>` — note if that collides with a policy.
5. **Existing `.claude/`:** does the repo already have `.claude/` content (agents, commands,
   settings)? List what exists; you will MERGE, never overwrite.
6. **Ticket system:** where tickets live (Jira, GitHub Issues, ADO, Linear). The runner
   takes the ticket ID + a brief as text — no integration is required, but record the ID
   format (e.g. `PROJ-123`) for examples.

**Checkpoint 0:** you can state the repo's source dirs, test command, lint command, CI
system, and default branch in one paragraph. Present this summary to the human before
proceeding.

---

## Phase 1 — Install

1. Copy the package's `.claude/` tree into the repo's `.claude/`, merging with anything that
   exists. Collision rule: never overwrite an existing file — if a filename collides
   (e.g. an agents file), keep the repo's version, note the collision, and surface it to the
   human at the end.
2. Append to the repo's `.gitignore` (create if missing):
   ```
   .claude/teams/state/*
   !.claude/teams/state/.gitkeep
   ```
3. Verify prerequisites on this machine: `git`, `gh` (authenticated: `gh auth status`),
   `jq`, and Claude Code with the Workflow tool. Report any that are missing rather than
   working around them.

**Checkpoint 1:** `ls .claude/workflows/team-run.js .claude/commands/team.md
.claude/teams/dev.yaml` all exist; `gh auth status` succeeds; state-dir gitignore present.

---

## Phase 2 — Model routing (ASK THE HUMAN)

Open `.claude/teams/model-routing.yaml`. The model names are placeholders: `strong`, `mid`,
`cheap`.

**Ask the human:** *"Which model identifiers does your Claude Code setup expose, and which
should map to strong / mid / cheap?"* Do not infer this from documentation or guess model
names — orgs expose different sets.

Apply the mapping with these invariants (explain them if asked):
- `decompose` and `review` always get the **strongest** tier — a wrong plan wastes every
  downstream token, and the review gate is what stops plausible-but-wrong changes.
- **Never map `review` to a cheaper tier than `implement`.**
- `effort` values stay as shipped unless the human overrides.

**Checkpoint 2:** no occurrence of `strong`, `mid`, or `cheap` remains in
`model-routing.yaml`; the review stage uses the strongest configured model.

---

## Phase 3 — Team config + context pack (the value step)

### 3a. Ownership zones
Edit `.claude/teams/dev.yaml` → `ownership:`. Derive the list from Phase 0: the source
directories this team may edit. The runner confines mutating stages to these zones plus
`tests/` and `docs/` equivalents; anything else is reported, not silently changed. Broad
zones are fine for a single dev team. **Ask the human to confirm the list** — one line, e.g.
*"Proposing ownership: src/, app/, lib/ — anything to exclude?"*

### 3b. Context pack
Rewrite `.claude/teams/context-packs/dev.md` from the shipped seed using Phase 0 findings.
This file is injected into EVERY agent in every run — it is the single highest-leverage
artifact you will produce. Structure (keep under ~12,000 characters, pointers not content):

- `## Map` — where things live: source dirs, test dirs, config, entry points, schema/types
  locations. File paths, not descriptions of file contents.
- `## Commands` — the exact install / test / lint / format / type-check commands from
  Phase 0, plus any required env prefixes.
- `## Trip-wires` — the landmines. Mine these from: `CONTRIBUTING.md`, PR templates, CI
  config quirks (e.g. "coverage gate fails on partial runs"), pinned dependency oddities,
  "do not touch" directories, flaky-test warnings in docs or comments. Ask the human:
  *"What are the 3–5 mistakes a new senior hire makes in their first week in this repo?"* —
  their answers are trip-wires, verbatim.
- `## Current state` — what's in flight that a run must not collide with (big refactors,
  frozen modules, release branches). Ask the human; date-stamp the section.

### 3c. Memory seed
Leave `.claude/teams/memory/dev.md` as the shipped template — runs append lessons to it
automatically. Do not pre-fill it.

**Checkpoint 3:** `dev.yaml` ownership matches the human-confirmed list; the context pack
contains real commands (no placeholders) and at least 3 trip-wires; pack length ≤ 12k chars.

---

## Phase 4 — Verify with a dry run

The runner supports fixture-driven dry runs: passing `args.fixtures` executes the full stage
skeleton with canned results — no real agents, no state writes, no branches.

1. Read the `args contract` comment block at the top of `.claude/workflows/team-run.js`.
2. Invoke the workflow with a minimal fixture set (every stage label → a canned result) and
   a fake ticket, e.g. `TICKET-000`, and confirm the returned trace lists the stages in
   order with your Phase 2 models attached.
3. If the trace is wrong (missing stages, wrong models), fix config — not the runner — and
   re-run.

**Checkpoint 4:** dry-run trace shows decompose → implement → test → docs → review → ci →
report with the mapped models.

---

## Phase 5 — First real dispatch (SMALL, with the human watching)

1. Ask the human for a real but SMALL ticket — a one-file bugfix or a small, well-specified
   endpoint. First runs surface config gaps; keep the blast radius small.
2. Dispatch per `.claude/commands/team.md`:
   `/team dispatch dev <TICKET-ID> "<one-paragraph brief with acceptance criteria>" small`
3. While it runs, watch with `/team status`.
4. When it completes, walk the human through the result: the PR link, the review-gate
   findings, the CI status, and the board entry. **The human merges. You never merge.**

**Checkpoint 5:** a PR exists, opened by the run; CI ran; nothing was merged by the runner.

---

## Failure modes you may hit (and the fix)

| Symptom | Cause → fix |
|---|---|
| `ill-specified` status | Brief too vague — decompose returned questions. Show them to the human, refine the brief, re-dispatch. This is a cheap, GOOD failure. |
| Run can't open a PR | `gh` unauthenticated or repo host isn't GitHub. Verify `gh auth status`; if not GitHub, stop and report — PR/CI steps need adaptation. |
| Stage agents can't find code | Context pack `## Map` paths wrong, or ownership zones too narrow. Fix the pack, not the runner. |
| CI gate loops red on pre-existing failures | The repo's suite was red before the run. Verify against the default branch; pre-existing reds are reported to the human, not fixed silently in an unrelated PR. |
| Branch name collides with policy | Adjust the human-facing convention: dispatch with a ticket ID whose lowercase form fits (`BRANCH` is `<ticket>-<team>` lowercased). |

## Boundaries (non-negotiable, repeat them in your final report)

- The runner **opens PRs and stops**. Never merges, never pushes the default branch.
- No deploys, no production data operations, no credential handling — those are documented
  as human ops steps in PR bodies.
- All state (`.claude/teams/state/`) is local runtime data, gitignored, safe to delete.
- Removing the framework = delete the added `.claude/` files and the gitignore lines.
  Nothing else in the repo is touched by installation.

## Final report to the human

End your implementation with: the Phase 0 summary, what you installed/merged, the model
mapping applied, the confirmed ownership zones, a link to the context pack for their review,
the dry-run trace, and (after Phase 5) the first PR link. Flag every collision and every
question you could not resolve.
