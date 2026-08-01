---
name: org-init
description: Materialize a customized agentic org into this project. Use when the user runs /org-init or asks to set up agentic teams, generate their org, or bootstrap the agentic-teams framework in a repo.
---

# /org-init — Materialize Your Agentic Org

Interview the user, then generate a **project-owned** agentic org into the
project's `.claude/` from the plugin's library. The project owns the output —
it keeps working if the plugin is uninstalled.

- Library root (the source of everything you copy): `${CLAUDE_PLUGIN_ROOT}/.claude/`
- Plugin version (for provenance headers): the `version` field of
  `${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json`
- Provenance header, added to EVERY generated file:
  - markdown: `<!-- agentic-org: v<version> source=<path> -->` placed
    on the line after the H1 title — UNLESS the file has YAML frontmatter, in
    which case frontmatter always wins: place it immediately after the closing
    frontmatter `---`, even when an H1 follows below it (agent files have both;
    the frontmatter position is correct for them). Either way, the provenance
    line MUST land within the file's first 12 lines — that's the window
    `/org-update` and `scripts/validate_org.py` scan; anything placed later is
    invisible to both.
  - yaml: `# agentic-org: v<version> source=<path>` as line 1
  - **`source=<path>` is always relative to `${CLAUDE_PLUGIN_ROOT}` (the plugin root),
    NEVER relative to the `.claude/` library subdirectory.** Concretely: prepend
    `.claude/` to the file's path inside the library. `/org-update` resolves upstream
    files as `${CLAUDE_PLUGIN_ROOT}/<source>` and as `git show v<version>:<source>` —
    both need the plugin-root-relative form, so getting this wrong breaks every future
    sync. One worked example per file type the wizard writes:

    | Generated file | Library file it came from | Correct `source=` |
    |---|---|---|
    | `agents/tech-lead.md` | `${CLAUDE_PLUGIN_ROOT}/.claude/agents/tech-lead.md` | `.claude/agents/tech-lead.md` |
    | `teams/dev.yaml` (from TEMPLATE) | `${CLAUDE_PLUGIN_ROOT}/.claude/teams/TEMPLATE.yaml` | `.claude/teams/TEMPLATE.yaml` |
    | `teams/context-packs/dev.md` (from TEMPLATE) | `${CLAUDE_PLUGIN_ROOT}/.claude/teams/context-packs/TEMPLATE.md` | `.claude/teams/context-packs/TEMPLATE.md` |
    | `org-memory/decisions.md` | `${CLAUDE_PLUGIN_ROOT}/.claude/org-memory/decisions.md` | `.claude/org-memory/decisions.md` |
    | `workflows/team-run.js` | `${CLAUDE_PLUGIN_ROOT}/.claude/workflows/team-run.js` | `.claude/workflows/team-run.js` |
    | `workflows/health-check.js` (a recipe) | `${CLAUDE_PLUGIN_ROOT}/.claude/workflows/recipes/health-check.js` | `.claude/workflows/recipes/health-check.js` |
    | `commands/team.md` | `${CLAUDE_PLUGIN_ROOT}/.claude/commands/team.md` | `.claude/commands/team.md` |

    Note the recipe case: the generated file moves from `workflows/recipes/` to
    `workflows/`, but `source=` still points at the library's `workflows/recipes/`
    path, since that's where the upstream actually lives.

## 1. Prerequisites (hard gate)

Run each check; on failure STOP and give the plain-language fix:

| Check | Command | Fix if it fails |
|---|---|---|
| Git repo | `git rev-parse --show-toplevel` | "Run this inside a git repository (`git init` first)." |
| GitHub CLI | `gh auth status` | "Install the GitHub CLI and run `gh auth login` — team-runs open PRs via `gh`." |
| Worktrees | `git worktree list` | "Your git is too old — team-runs isolate work in worktrees (git ≥ 2.5)." |
| jq | `jq --version` | "Install `jq` — the `/team` board updates use it." |
| Python 3 + PyYAML | `python3 -c "import yaml"` | "Install Python 3 and `pip3 install pyyaml` — the validator in step 8 needs both." |

Also note (warn, don't block): if the repo has no CI configured on PRs, the
ci-green gate will report red on every run — recommend adding at least a test
workflow before the first dispatch.

## 2. Existing-org check (idempotence)

### 2a. Refuse to run against the library itself

Run this FIRST:

```bash
grep -l '"name": *"agentic-org"' .claude-plugin/plugin.json 2>/dev/null
```

If that prints a path, the current project **is the agentic-org library**, not a
project to be staffed. **Stop immediately** and say so.

Materializing here would be destructive and silent: the wizard writes customized
agents to `.claude/agents/`, which is exactly where the library's generic agent
identities live, so it would fill their PROJECT-CONTEXT blocks with this repo's
context and ship project-specific agents to every adopter on the next release.
The team-yaml check in 2b does not catch it — the library has no team yamls, so
that check reads "no existing org" and proceeds with a fresh materialization.

To exercise the delivery pipeline on the library repo itself, hand-write team
yamls and context packs per the manual quickstart instead. Do not run this wizard.

### 2b. Existing-org check

Run:

```bash
ls .claude/teams/*.yaml 2>/dev/null | grep -v -E '/(TEMPLATE|model-routing)\.yaml$'
```

This returns cleanly empty (no output, no error) both when `.claude/teams/`
has no team yamls yet AND when `.claude/` doesn't exist at all — either shape
means "no existing org," and empty output is that signal, not a failure.

If any team yaml exists (excluding `TEMPLATE.yaml` and `model-routing.yaml`):
say the org already exists and offer exactly two paths — **update** (invoke
the org-update skill and stop) or **extend** (continue, but only ADD new
teams/agents/recipes; skip every file that already exists and list the skips
at the end). NEVER silently overwrite an existing org file.

### 2c. Prior-Claude-Code check (runs even when 2b is empty)

An empty 2b means "no org built by this wizard." It does **not** mean the
project has no `.claude/` worth protecting. A project already using Claude Code
commonly has hand-written agents, commands, or workflows and no team yamls at
all — that is the single most likely adopter profile, and a fresh
materialization would overwrite those files.

Run:

```bash
# RECURSIVE on purpose. A flat `ls .claude/agents/*.md` misses agents kept in
# subdirectories, and that is common: on a real project this check reported 2
# agents when 33 existed (agents/engineering/, agents/ai_ml/, agents/business/…),
# under-reporting by 94% and making an organised project look nearly clean.
find .claude/agents -name '*.md' 2>/dev/null
find .claude/commands -name '*.md' 2>/dev/null
find .claude/workflows -name '*.js' 2>/dev/null
```

If anything is listed, do **not** treat this as a clean project. Compute the
collisions before writing anything, at **two** levels:

- **Path collisions** — for every file this run would materialize, does that exact
  path already exist?
- **Name collisions** — does an agent of the same *name* already exist anywhere in
  the tree, even at a different path? A project keeping
  `agents/engineering/backend-expert.md` would otherwise receive a SECOND
  `backend-expert` at `agents/backend-expert.md`: no path collision, two identities
  with one name, and nothing says which one a lead dispatches. Treat a name
  collision as a collision — preserve theirs by default.

Then show the CEO the collision list and offer exactly three paths:

- **preserve** (default, recommended) — materialize only the files that do not
  already exist, skip every collision, and list the skips at the end. Their
  agents keep working; the org is built around them.
- **back up and replace** — copy each colliding file to `<name>.pre-org-init.md`
  first, then write. Only on explicit confirmation, naming the files.
- **abort** — write nothing.

**Never overwrite a pre-existing file without confirmation, in any mode.**
Extend-mode's skip rule is not a substitute for this check: extend mode only
activates when 2b finds team yamls, so a project with custom agents and no
teams would otherwise fresh-materialize straight over them.

A skipped agent is not a silent gap. If a collision means a roster agent was
not materialized, say so in the handover — the team lead will route to that
`agentType` and get whatever the project's own version does.

## 3. Interview (one question at a time)

Use AskUserQuestion where options fit; keep it to ~6 questions:

1. **Product** — what is this project, in one sentence? (Seeds team missions and packs.)
2. **Stack** — language(s), framework(s), and the exact formatter / linter /
   type-checker / test commands. VERIFY against the repo (package.json,
   pyproject.toml, Makefile, go.mod…) instead of trusting the answer blindly.
3. **Functions** (multi-select) — which parts of the org to staff:
   delivery (code → gated PRs) · product advisory · growth/marketing · platform-ops.
   Say what the two shapes actually produce, so the choice is informed: a **delivery**
   team returns a code-reviewed, CI-green PR you merge; an **advisory** team returns a
   written recommendation that a non-author critique gate has attacked, and it creates
   no branch and no PR. Offer at least one advisory team to anyone who picks product,
   growth, or business-ops work — that work has no PR to gate, and running it through
   the delivery pipeline would demand a CI gate it can never pass.
4. **Model tiers** — which model identifiers this setup exposes for
   strong / mid / cheap (suggest what you know is available; these replace the
   placeholders in model-routing.yaml).
5. **Ticket convention** — Linear/Jira/GitHub-issue prefix, or free-form
   (used in dispatch examples).
6. **Recipes** (multi-select) — install recurring workflows. Describe each in one
   line so the choice is informed, and recommend `triage` to everyone:

   | Recipe | What it does |
   |---|---|
   | `triage` | Unstructured human report → diagnosed, deduped, prioritized work. The entry point from "this is broken" into a dispatchable brief. Read-only. |
   | `health-check` | Run a set of independent checks in parallel and report what is red. Read-only. |
   | `audit` | Sweep a target against a checklist, then adversarially verify each finding. Read-only. |
   | `retro` | Read recent run telemetry and memory, write a retrospective, recommend which lessons should graduate into a context pack. |
   | `batch-author` | Author N entries that all land in ONE file (i18n catalogs, fixtures, config registries, an OpenAPI spec). Parallel authoring, single serialized writer. |
   | `release-gate` | Parallel static checks plus a strictly serial exclusive-resource chain, ending in an artifact smoke-launch. Verdict: SHIP / NO-SHIP / INCOMPLETE. |
   | `consistency-sweep` | Sweep every surface against a locked terminology/claims contract, verifying each violation in its own context. Read-only. |
   | `first-run` | Probe the signup→first-value journey for defects that only appear with zero data and no prior state. Read-only. |
   | `dependency-probe` | Probe every third-party dependency against production failure modes, then ask which single change breaks the most at once. Read-only. |
   | `state-reconcile` | Detect drift between what a tracker claims and what reality shows (board vs git, roadmap vs shipped), via two blind gatherers. Report-only unless write-back is explicitly authorized. |
   | `landscape-check` | Check whether the ecosystem now ships something you still maintain yourself, comparing by function rather than by name. Says what to stop maintaining and what is still genuinely yours. Read-only. |

   `batch-author` is worth flagging specifically: it covers the case ownership
   zones and worktrees structurally cannot — many independent work items that all
   have to be written into the same file.

## 4. Codebase scan (read-only)

Explore enough to draft each selected team's context pack: top-level layout,
where each candidate ownership zone lives, project commands, and 2–3 obvious
trip-wires (odd conventions, generated dirs, migration rules). POINTERS, NOT
CONTENT — never paste code into a pack.

### 4a. Integration detection (evidence only)

While scanning, also build a candidate list of the **third-party integrations
this repo actually depends on** — Stripe, Supabase, Twilio, Shopify, Kafka,
Airflow, Snowflake, Unity, whatever it happens to be. Step 5a turns some of
these into generated agents, so the quality of this list is the quality of that
generation. Look at, in roughly this order of strength:

| Signal | Where |
|---|---|
| Direct dependency declaration | `package.json`, `pyproject.toml` / `requirements.txt`, `go.mod`, `Gemfile`, `Cargo.toml`, `composer.json`, `*.csproj`, `Package.swift` |
| Import / SDK usage in source | `grep -rn "stripe\|@supabase/" src/ app/` and equivalents — the SDK actually being called |
| Config directory or service config file | `supabase/`, `terraform/`, `docker-compose.yml`, `vercel.json`, `serverless.yml`, `fly.toml`, `firebase.json` |
| Environment-variable names | `.env.example`, `.env.sample`, CI workflow `env:` blocks, deployment config |
| Integration-shaped source paths | webhook route handlers, client/singleton modules (`lib/stripe.ts`), migration dirs, generated types |

**A guess is not evidence.** For every candidate, record a concrete
`path:line` you can show the user. If you cannot point at a file in this repo
proving the dependency is used, the candidate does not exist — drop it. Do not
infer an integration from the user's answers in step 3, from the product
description, from a framework's reputation, or from what a project like this
"usually" has. The interview cannot create evidence; only the repo can.

**Direct, not transitive.** A name that appears only in a lockfile
(`package-lock.json`, `poetry.lock`, `go.sum`) is a transitive dependency of
something else, and staffing an agent for it is nonsense. Require BOTH a direct
declaration in a manifest AND at least one second signal (an import, a config
file, or an env var). One signal alone is a lead, not a finding.

Carry the evidence forward verbatim — step 5a shows it to the user, and the
generated agent's body is written from it.

## 5. Roster selection (curate roles, generate integrations)

Staff teams from the library roster (`${CLAUDE_PLUGIN_ROOT}/.claude/agents/`):

| Function | Team yaml | type/output | gates | Lead | Specialists (pick for the stack) | roster.test |
|---|---|---|---|---|---|---|
| Delivery | `dev.yaml` (split into `backend.yaml`/`frontend.yaml` only when zones are truly disjoint) | delivery/pr | `[code-review, ci-green]` | tech-lead | backend-expert, frontend-expert, api-expert, database-expert — as the stack requires; `software-engineer` when none of them fits (see below) | qa-tester |
| Product advisory | `product.yaml` | advisory/document | `[critique]` | product-manager | ux-designer, analytics-expert | code-reviewer (fact-check gate) |
| Growth | `growth.yaml` | advisory/document | `[critique]` | marketing-expert | copywriter | legal-expert (compliance gate) |
| Platform-ops | `platform.yaml` | delivery/pr | `[code-review, ci-green]` | tech-lead | cloud-infra-expert, sre, security-expert | qa-tester |

**Delivery specialists when no specialist fits the stack.** The four named above are
web-service-shaped: `backend-expert` assumes routes and an ORM, `frontend-expert` assumes a
browser UI framework, `api-expert` assumes a REST/OpenAPI contract, `database-expert` assumes
a SQL schema. Decide from the step-4 scan, not from the stack's name. If the scan found
**no web/API/DB surface** — no HTTP server or route definitions, no API contract/schema
files, no database schema or migration directory — do NOT staff the least-wrong one and rely on its
PROJECT-CONTEXT block to contradict a body describing the wrong stack. Staff
`software-engineer`: the stack-agnostic implementer seat, whose body is engineering method
(read the surrounding idiom first, discover the project's real build/test/lint commands,
smallest change, pin behavior in the project's own testing idiom) and which takes every
specific from its PROJECT-CONTEXT block. Typical cases: game-engine projects, CLIs, libraries
and SDKs, data/ETL pipelines, embedded and systems code, build/dev tooling, and
docs- or config-heavy repos. In a **mixed** repo, staff both — the fitting specialists for the
surfaces that exist, plus `software-engineer` for the parts none of them covers; the decompose
stage then picks per work package. Its PROJECT-CONTEXT block matters more than most: name the
language(s), the verified build/test/lint commands, where source and tests live, and which
directories are generated or vendored.

On a **delivery** team `roster.test` is the agent that writes tests. On an **advisory**
team it is the **critique-gate seat**: the non-author who attacks the document before a
human reads it. It must never be the same agent as the lead — a lead seated there is
ignored and the runner falls back to `code-reviewer`, because an author may not clear its
own work. An advisory team's ownership zones are DOCUMENT paths (`docs/product/`,
`docs/business/`, …), never application source: an advisory run is forbidden from editing
source at all, so a source zone on an advisory team is a bug in the org chart.

Always materialize `code-reviewer`, `debug-expert`, and `docs-author` even if no
roster names them — the runner hard-requires those three agentTypes (advisory runs use
`code-reviewer` and `debug-expert` as the two independent refuters behind the critique gate).

### 5a. Integration specialists (the ONE thing you may generate)

Everything above this line is curation. This step is the single exception, and it exists
because agent identities fall on two axes that behave completely differently:

- **Role identities** — backend, frontend, api, database, security, sre, qa, docs, the
  generalist. Enumerable, finite, and the library above already covers them.
  **NEVER generate one of these.** If the need is "someone who writes server-side code",
  that is `backend-expert`; if the stack has no web/API/DB surface at all, that is
  `software-engineer`. Inventing a second one splits routing between two agents with the
  same remit and the decompose stage picks arbitrarily between them.
- **Integration / domain identities** — Stripe, Supabase, Twilio, Shopify, Kafka, Airflow,
  Snowflake, Unity, Algolia, Segment. **Unbounded and un-enumerable** — no library can
  ever cover this axis, so curation structurally cannot reach it. This is the gap a human
  fills by hand-writing an agent today, and it is what you generate here.

**The forbidden-duplicate test.** Before generating anything, ask: *would this agent's
remit survive the vendor disappearing?* If yes it is a role, it already exists, staff
that instead. Enforce it mechanically too:

- The name MUST be the integration's own name — `stripe-expert`, `supabase-expert`,
  `kafka-expert`. NEVER a role word with a qualifier (`backend-expert-2`,
  `payments-backend`, `api-expert-stripe`, `senior-frontend`).
- Run `ls "${CLAUDE_PLUGIN_ROOT}/.claude/agents/"` first. If the name you are about to
  generate is already there — or is a synonym of one that is — do not generate it. Staff
  the library agent.
- No generated agent may be a team's `lead` or `roster.test`. Those seats are role seats
  (`tech-lead`, `qa-tester`, `code-reviewer`…); an integration specialist is always a
  `specialists` entry.

**Which few actually matter (hard cap).** A repo with 60 dependencies must not produce
60 agents. From the 4a candidate list, keep only those where ALL of these hold:

1. It is load-bearing for the product's core value — remove it and the product stops
   doing its main job.
2. It has a real operational surface the project must get right: webhooks and signature
   verification, sandbox-vs-live credentials, migrations, quotas and rate limits, retry
   and idempotency semantics, generated types, its own CLI. A library called from three
   lines in one file has no such surface — a role specialist plus its PROJECT-CONTEXT
   block already handles it.
3. Its footprint is non-trivial: more than a couple of files touch it.

Then rank the survivors by footprint (files touched) and cap: **at most 3 per team, and
at most 5 across the whole org.**

**Propose before generating — never generate silently.** Show the ranked candidates with
their evidence (`path:line` per signal) and the proposed name and one-line remit for each,
mark which are inside the cap, and let the user add, drop, or rename. An unused transitive
dependency must not become a staffed agent, and only the user knows which of two equally
well-evidenced integrations is actually strategic. Generate exactly what they confirm; if
they confirm none, generate none and continue — zero generated agents is a normal outcome.

**What each generated agent must contain.** It is materialized in step 6 alongside the
copied agents and is held to every check in `scripts/validate_org.py` (see the "Adding an
agent to a materialized org" checklist in that file's module docstring — it is the spec):

1. **Frontmatter** — `name:` equal to the filename stem, plus `team:`, `tools:`, `model:`
   copied from the closest library specialist's frontmatter shape (an integration
   specialist that writes code gets `team: engineering` and the `backend-expert` tool set).
2. **`description:` — this is routing logic, not prose.** Read
   `${CLAUDE_PLUGIN_ROOT}/.claude/agents/backend-expert.md`'s description and follow its
   shape exactly: what the agent IS for, then `Do NOT use for …`, naming the alternative
   agent by name. A generated integration agent MUST hand general work in its area back to
   the role specialist and reserve itself for the integration's own specifics — otherwise
   it competes with `backend-expert` for every server-side request. Concretely:

   ```
   description: Use this agent for Stripe-specific work in this repo — Checkout and Billing
     session creation, webhook signature verification and event handling in
     app/api/webhooks/stripe/route.ts, price/product ID wiring and its env vars, subscription
     lifecycle and proration, test-vs-live key separation. Do NOT use for general server-side
     routes, ORM models, or auth (use backend-expert), for REST contract and route layout
     (use api-expert), or for the schema and migrations behind billing tables (use
     database-expert).
   ```

3. **Provenance marker** — instead of a library `source=` line, within the first 12 lines
   (same placement rule as any agent: immediately after the closing frontmatter `---`):

   ```
   <!-- agentic-org: project-owned kind=integration generated-by=/org-init v<version> — no upstream library file; /org-update never syncs or overwrites it -->
   ```

   The literal token `agentic-org: project-owned` is what the validator recognises and
   what `grep -rn 'agentic-org: project-owned' .claude/agents/` finds; the rest of the
   line is for the human reading the file. Do NOT omit the header instead — a file with
   no header is indistinguishable from one whose header was forgotten, and the validator
   rejects it.
4. **Body grounded in the scan, not in vendor documentation.** Write it from what step 4a
   actually found: where the integration is configured in THIS repo, which files call it,
   which env vars it reads, its migrations/webhooks/generated-type paths, and the
   project's own conventions and trip-wires around it. **If you cannot cite a file in this
   repo for a claim, leave the claim out.** Never paste vendor docs, API reference tables,
   or version-specific snippets — they go stale, they are not this project, and a wrong
   one is worse than a gap. Keep it comparable in length to a library agent; a short,
   correct, pointer-driven body beats a long one.
5. **A filled PROJECT-CONTEXT block** — exactly one
   `<!-- PROJECT-CONTEXT:BEGIN -->` / `<!-- PROJECT-CONTEXT:END -->` pair, with this
   project's specifics between them and no `Filled by /org-init` sentinel.
6. **Registered in `AGENTS.md`** — add a roster line whose first token is the agent name,
   under the relevant team block, in the same format as the surrounding lines. Note this
   makes the project's `AGENTS.md` differ from the library's; `/org-update` will flag it
   CUSTOMIZED, which is correct and expected. Say so in the handover.
7. **Staffed on a roster** — add the name to that team yaml's `specialists`. An agent on
   no roster is dead weight and the validator warns about it.

## 6. Materialize (staging first)

Build EVERYTHING under `.claude/.org-init-staging/` first. Only after all
generation succeeds, move files into their real `.claude/` locations
(extend-mode: skip existing files and record the skip), then delete the staging
dir. A failed generation must leave the project untouched: on failure, remove
the staging directory before reporting the error.

Generate, each file with its provenance header:

1. **Agents** → `agents/<name>.md` for every rostered agent + the three
   hard-required ones + `AGENTS.md` (copied as-is, plus provenance). For each
   agent: copy the library file, then REPLACE the body between
   `<!-- PROJECT-CONTEXT:BEGIN -->` and `<!-- PROJECT-CONTEXT:END -->` with
   project specifics — stack, the key paths for this agent's remit, project
   commands, conventions. Leave everything outside the markers untouched.
   Any integration specialists the user confirmed in step 5a are **generated**
   into this same staging dir rather than copied — they carry the
   `agentic-org: project-owned` marker in place of a `source=` header, and
   5a is their full contract.
   The materialized `AGENTS.md` lists the FULL library roster even though only
   some agents were staffed — a team lead reading it could route to an
   agentType that doesn't exist in this project. Prepend a short header note
   (2-3 lines, above the existing content) naming which agents were actually
   materialized in this project (`ls .claude/agents/*.md`) versus which remain
   available in the library only (install via `/org-update` or by hand). Order
   top-to-bottom: H1 title, then the provenance comment (line 2, per the
   provenance-header rule above — this file has no frontmatter), then the
   header note, then the original registry body unchanged. Do NOT rewrite the
   rest of the registry.
2. **Teams** → `teams/<team>.yaml` from `teams/TEMPLATE.yaml` (drop the
   template comments): name = filename stem, type/output per the table,
   one-line mission from the interview, roster, REAL ownership zones (every
   path must exist), `context_pack: context-packs/<team>.md`, the template's
   budget_defaults, `routing: {}`, and `gates` MATCHING the output mode —
   `gates: [code-review, ci-green]` for `output: pr`, `gates: [critique]` for
   `output: document`. The validator in step 8 rejects a mismatch: an advisory
   run opens no PR, so `ci-green` names a check it can never satisfy. A
   document-output team whose ownership zones do not yet exist needs those doc
   directories created (with a seed file) before validation will pass.
3. **Context packs** → `teams/context-packs/<team>.md`: first line
   `# Context Pack — <team>`, provenance on line 2, staleness line with today's
   date and "(org-init)" — this line MUST contain the literal token
   `Staleness:`; follow the shape of
   `${CLAUDE_PLUGIN_ROOT}/.claude/teams/context-packs/TEMPLATE.md` — then
   `## Map` / `## Trip-wires` / `## Current state` from the scan. For a fresh
   org, Current state = "fresh org — nothing in flight". HARD CAP 12,000
   chars.
4. **Team memory seeds** → `teams/memory/<team>.md`: first line
   `# Team lessons — <team>`, provenance on line 2.
5. **Org memory** → copy the three files from
   `${CLAUDE_PLUGIN_ROOT}/.claude/org-memory/` (keep their canonical first
   lines; provenance on line 2; keep the `## Candidates (pending curation)`
   heading in lessons.md). Seed decisions.md with 1–3 dated entries from the
   interview (stack choice, org shape). Every org-memory file is capped at
   8,000 chars — stay under it.
6. **Runner** → copy `workflows/team-run.js` VERBATIM, with the provenance
   comment prepended as line 1 (`// agentic-org: v<version> source=…`, above
   `export const meta`). Change nothing else — this file is library-synced.
7. **Recipes** → copy each recipe the user selected from
   `workflows/recipes/` into `workflows/` (provenance as line 1, same as the runner).
8. **Command** → copy `commands/team.md` → `.claude/commands/team.md` with
   provenance after the H1 (the project keeps `/team` even without the plugin).
9. **Routing** → `teams/model-routing.yaml` from the library file with
   `strong` / `mid` / `cheap` replaced by the user's identifiers. The `review`
   stage MUST use the same model as `decompose`, and `review`'s effort MUST be
   `high`, `xhigh`, or `max`. The library file's comment block above `defaults:`
   tells the *wizard* to do this substitution — once you've done it, that
   instruction is stale (it describes a still-pending action that already
   happened). Replace it with a short factual note instead: which identifier
   was chosen for each of `strong` / `mid` / `cheap`, and a one-line restatement
   that `review` must never be demoted below the strongest tier. Keep the rest
   of the file (the philosophy comment, the top-level `fallback:` entry, the
   `defaults:` block structure) unchanged — `fallback` is the route a failed
   stage's retry escalates to, so its placeholder gets substituted like any
   other and it must land on a strong, reliably available model.
10. **State dir** → `teams/state/.gitkeep` (empty file). **Add it; never remove
    what is already there.** A project may already keep its own ignore rule inside
    `teams/state/` (e.g. a local `.gitignore` holding `*` + `!.gitignore`), which is
    a valid way to achieve the same result. On a real run this step replaced such a
    file, and the net effect was equivalent — but the guarantee this wizard makes is
    "never overwrite a pre-existing file without confirmation", and **deleting is
    stronger than overwriting**. If `teams/state/` already contains an ignore file,
    keep it, still write `.gitkeep`, and say in the handover that both are present
    and either alone would suffice.

## 7. Wire the project

Append to the project's `.gitignore` (create it if missing), only the lines not
already present:

```
.claude/teams/state/*
!.claude/teams/state/.gitkeep
```

## 8. Validate (hard gate)

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/validate_org.py" --project-root "$(git rev-parse --show-toplevel)"
```

Exit 0 required. On failure: fix every reported error and re-run. Do NOT hand
over an org that fails validation.

## 9. Hand over

Report: the org chart (`ls .claude/teams/*.yaml`), agents materialized, recipes
installed, and a first-dispatch example using the user's ticket convention.

List agents in two groups, because they behave differently from here on: the ones
**copied from the library** (which `/org-update` keeps in sync) and the ones
**generated for this project** in step 5a (`grep -rln 'agentic-org: project-owned'
.claude/agents/`), which this project now owns outright — `/org-update` will never
sync or overwrite them, so improving them is the project's job. If any were
generated, also say that `AGENTS.md` now carries their roster lines and will be
reported CUSTOMIZED by the next `/org-update`, which is expected.

```
/team dispatch <team> <TICKET-1> "<one concrete starter task from the interview>" small
```

If any recipes were installed, also show how to invoke each one — they run
directly through the Workflow tool (not `/team`), and every one needs a
dispatcher-supplied `timestamp` (workflow scripts cannot call `Date`):

```
Workflow({name: 'health-check', args: {checks: [{name: 'api-up', instructions: 'curl the /health endpoint and confirm 200'}], timestamp: '<ISO8601 now>'}})
Workflow({name: 'retro', args: {timestamp: '<ISO8601 now>', lookback: 15}})
Workflow({name: 'audit', args: {target: 'src/auth/', checklist: ['secrets in code', 'unvalidated input reaching queries'], timestamp: '<ISO8601 now>'}})
```

Offer to commit the org on a feature branch (`chore/agentic-org-init`) — never
commit without the user's go-ahead, never push to the default branch. Close by
noting `/org-update` exists for syncing future library improvements.
