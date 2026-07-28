export const meta = {
  name: 'team-run',
  description: 'Runs a dev team on one ticket and opens a reviewed, CI-green PR for human approval.',
  whenToUse:
    'Dispatch via the /team command (resolves team config, registers the board entry, generates runId/timestamp). Direct invocation works too: a setup agent resolves config from .claude/teams/. Passing args.fixtures makes it a DRY RUN: no real agents, no state writes, returns the stage trace.',
  phases: [
    { title: 'Setup', detail: 'resolve team config (skipped when /team dispatch injects it)' },
    { title: 'Decompose', detail: 'team lead: work packages, test plan, doc targets, risks' },
    { title: 'Build', detail: 'implement packages sequentially on the run branch, then tests + docs' },
    { title: 'Gates', detail: 'code-review gate + full-CI gate, bounded revision loop' },
    { title: 'Report', detail: 'telemetry + board/event/memory writes' },
  ],
}

// =============================================================================
// team-run.js — generic, config-driven team runner (Agentic Teams Framework)
// -----------------------------------------------------------------------------
// This runner is INTENTIONALLY project-agnostic. Everything project-specific
// lives in .claude/teams/ config, injected at dispatch or resolved in Setup:
//
//   CONFIG CONTRACT (args.config, or resolved from .claude/teams/<team>.yaml):
//   {
//     mission:   string   — one-line team charter, injected into decompose
//     roster:    { lead: <agent>, specialists: [<agent>...], test: <agent> }
//     ownership: [<path>...]  — file zones this team may edit (plus tests/ + docs/)
//     routing:   { <stage-class>: {model, effort} }  — global defaults merged
//                with the team yaml's overrides (team wins per stage class).
//                Stage classes: decompose, implement, write-tests, docs-author,
//                mechanical, review, revision-fix, librarian. Plus the non-stage
//                key `fallback: {model, effort}` — the route a failed stage's
//                retry escalates to (model-routing.yaml's top-level `fallback:`).
//     pack:      string   — the FULL context-pack markdown (pointers, trip-wires)
//     memory:    string   — the FULL team-lessons markdown ("" if absent)
//     orgMemory: string   — concatenated .claude/org-memory/ markdown ("" if absent)
//   }
//
//   HOST CONTRACT (provided by the Workflow runtime):
//     agent(prompt, opts)        — spawn a subagent; may THROW; returns null-ish
//                                  on no-report. opts: {label, phase, model,
//                                  effort, agentType, isolation, schema}
//     budget.spent() / .remaining()  — token accounting
//     phase(name) / log(msg)     — progress reporting
//     args                       — the dispatch args (object OR JSON string)
//
//   CORE INVARIANT (never edit away): this runner OPENS a PR and STOPS. It NEVER
//   merges and NEVER pushes to the default branch. Merge approval is always human.
// =============================================================================

// Runner identity. BUMP THIS WITH .claude-plugin/plugin.json's version — it rides in
// every telemetry record so a deployed (possibly forked) copy can report what it is.
const RUNNER_VERSION = '0.3.0'

// ---- args contract -------------------------------------------------------
// {
//   team: 'backend',                          // matches .claude/teams/<team>.yaml
//   ticket: 'TICKET-123',
//   brief: 'concrete task instructions',
//   size: 'small' | 'medium' | 'large',       // TELEMETRY LABEL ONLY — recorded, drives nothing
//   runId: 'backend-ticket-123-20260101T1030',// dispatcher-generated (no Date in scripts)
//   timestamp: '2026-01-01T10:30:00-05:00',   // dispatcher-generated
//   config?: { mission, roster, ownership, routing, pack, memory },  // injected by /team dispatch
//   maxRounds?: 3,                            // review-gate budget (legacy name)
//   maxReviewRounds?: 3, maxCiAttempts?: 3, maxGateRounds?: 6,  // per-gate budgets
//   maxCiInfraReruns?: 2,                     // infra-only CI reds re-run without spending a round
//   fixtures?: { '<stage label>': <canned result> },  // presence ⇒ DRY RUN
// }
// Some callers deliver args as a JSON string — normalize before validating.
let A = args || {}
if (typeof A === 'string') {
  try {
    A = JSON.parse(A)
  } catch (e) {
    return { error: 'team-run: args arrived as an unparseable string — pass a JSON object' }
  }
}
if (A === null || typeof A !== 'object' || Array.isArray(A)) {
  return { error: 'team-run: args must be a JSON object' }
}
const missing = ['team', 'ticket', 'brief', 'runId', 'timestamp'].filter((k) => !A[k])
if (missing.length) return { error: `team-run: missing required args: ${missing.join(', ')}` }

const MAX_ROUNDS = A.maxRounds || 3
// Review and CI are independent gates and get independent budgets: a mechanical CI
// fix must not spend a review round. Defaults reproduce v0.1.0 behaviour (3 review
// rounds, 3 CI attempts); maxRounds still sets the review budget for older callers.
const MAX_REVIEW_ROUNDS = A.maxReviewRounds || MAX_ROUNDS
const MAX_CI_ATTEMPTS = A.maxCiAttempts || 3
// Overall ceiling on gate iterations so decoupling the two budgets cannot run away.
const MAX_GATE_ROUNDS = A.maxGateRounds || MAX_REVIEW_ROUNDS + MAX_CI_ATTEMPTS
// A CI red with NO code cause (runner capacity, queue, quota, provider outage) is re-run
// instead of code-fixed, and the re-run does not spend a gate round. This ceiling is what
// keeps that refund from being an unbounded path: a permanently degraded runner exhausts
// the re-runs and the run then terminates through the normal CI-attempt budget.
const MAX_CI_INFRA_RERUNS = A.maxCiInfraReruns || 2
const DRY = !!A.fixtures
const BRANCH = `${A.ticket.toLowerCase()}-${A.team}`
const trace = []
const stages = []
const lessons = []
const orgLessons = []
let pr = null

// call(): the ONLY way stages invoke agents. Dry-run records the trace and returns
// the fixture; live runs record per-stage token spend for /model-eval telemetry.
const call = async (label, phaseName, prompt, opts = {}) => {
  if (DRY) {
    trace.push({
      label,
      model: opts.model || 'inherit',
      effort: opts.effort || 'inherit',
      agentType: opts.agentType || 'workflow',
    })
    return A.fixtures[label] !== undefined ? A.fixtures[label] : null
  }
  const before = budget.spent()
  // agent() can THROW (e.g. a StructuredOutput retry cap on an unparseable report) —
  // convert throws to null so the withRetry/blocked policy governs instead of killing the run.
  let res = null
  let err = null
  try {
    res = await agent(prompt, { label, phase: phaseName, ...opts })
  } catch (e) {
    err = String((e && e.message) || e).slice(0, 200)
    log(`${label}: agent threw (${err}) — treating as stage failure`)
  }
  // A null return used to record ok:false and NOTHING else, so a blocked run's telemetry
  // was diagnostically empty and the only reason a human ever got was "failed twice".
  // Every failure now carries a reason and names the route that produced it.
  if (!err && res == null) log(`${label}: no report from ${opts.model || 'inherit'}/${opts.effort || 'inherit'} — treating as stage failure`)
  stages.push({
    label,
    model: opts.model || 'inherit',
    effort: opts.effort || 'inherit',
    tokens: budget.spent() - before,
    ok: res != null,
    ...(err
      ? { error: err }
      : res == null
        ? { error: `no report returned by ${opts.model || 'inherit'}/${opts.effort || 'inherit'} — model unavailable, refusal, or an unusable report` }
        : {}),
  })
  if (res && Array.isArray(res.lessons)) lessons.push(...res.lessons.map((l) => ({ stage: label, lesson: l })))
  if (res && Array.isArray(res.orgLessons)) orgLessons.push(...res.orgLessons.map((l) => ({ stage: label, lesson: l })))
  return res
}

// The route a failed stage's retry ESCALATES to. A stage can fail at the MODEL level —
// capacity, availability, a provider-side error — and a retry that changes nothing cannot
// clear that (two runs died at decompose on the same model at the same minute; the identical
// brief succeeded later elsewhere). Tunable via the routing file's top-level `fallback:`
// entry; the default is the same conservative tier r() uses for a missing stage class.
// Reads cfg lazily because Setup's own config stage runs through withRetry.
const fallbackRoute = () => (cfg && cfg.routing && cfg.routing.fallback) || { model: 'opus', effort: 'high' }

// Failure policy: one retry (escalated to the fallback model); second failure → caller blocks.
const withRetry = async (label, phaseName, promptFn, opts = {}) => {
  const first = await call(label, phaseName, promptFn(false), opts)
  if (first) return first
  const fb = fallbackRoute()
  const retryOpts = { ...opts, ...(fb.model ? { model: fb.model } : {}), ...(fb.effort ? { effort: fb.effort } : {}) }
  if (retryOpts.model !== opts.model) log(`${label}: retrying on fallback model ${retryOpts.model} (primary ${opts.model || 'inherit'} returned nothing)`)
  return call(`${label}:retry`, phaseName, promptFn(true), retryOpts)
}

const blocked = async (stage, note) => {
  await persist('blocked', { stage, pr: typeof pr !== 'undefined' ? pr : '' })
  // Carry the failing stage's recorded reason into the note, so the run that reaches a
  // human says WHY it stopped instead of only that it stopped twice.
  const why = stages.filter((s) => s.error && (s.label === stage || s.label === `${stage}:retry`)).map((s) => s.error).pop()
  return {
    runId: A.runId, team: A.team, ticket: A.ticket, status: 'blocked', stage,
    note: note || `stage ${stage} failed twice — needs human arbitration${why ? ` (last: ${why})` : ''}`,
    branch: BRANCH, trace: DRY ? trace : undefined,
  }
}

// persist(): write board/events/runs state on an EARLY exit (blocked / ill-specified).
// The final Report phase has its own writer; this covers every `return` that exits first.
// DRY runs and setup-stage failures (cfg still null) are both guarded.
const persist = async (statusVal, opts = {}) => {
  if (DRY) return
  const m = (cfg && cfg.routing && cfg.routing.mechanical) || { model: 'sonnet', effort: 'low' }
  const runObj = {
    runId: A.runId, team: A.team, ticket: A.ticket, size: A.size || 'medium',
    runnerVersion: RUNNER_VERSION,
    timestamp: A.timestamp, branch: BRANCH, pr: opts.pr || '', status: statusVal,
    stage: opts.stage || '', stages,
  }
  // The event type carries the ACTUAL terminal status — hardcoding 'blocked' here made
  // 'ill-specified' indistinguishable from a stage failure in events.jsonl.
  const evt = {
    ts: A.timestamp, run: A.runId, team: A.team,
    type: statusVal === 'pr-ready' ? 'pr_opened' : statusVal,
    ticket: A.ticket, pr: opts.pr || '',
  }
  await call(
    'report:state:early',
    'Report',
    `Persist team-run state after an early exit. Work in the MAIN repo checkout (run \`git rev-parse --show-toplevel\` from your CWD; use absolute paths — do NOT cd into any worktree). All paths are under <repo>/.claude/teams/state/ — create dirs if missing (mkdir -p state/runs), and seed board.json with {"runs":[]} if absent.

1. Write EXACTLY this JSON to state/runs/${A.runId}.json:
${JSON.stringify(runObj)}

2. Append EXACTLY this line to state/events.jsonl:
${JSON.stringify(evt)}

3. Update state/board.json with jq: find .runs[] entry with .id=="${A.runId}" and set .status="${statusVal}", .pr="${opts.pr || ''}", .branch="${BRANCH}"; if no entry exists, append {"id":"${A.runId}","team":"${A.team}","ticket":"${A.ticket}","status":"${statusVal}","branch":"${BRANCH}","pr":"${opts.pr || ''}","worktree":"","ts":"${A.timestamp}"}.

Do not commit or push anything. State files under state/ are gitignored runtime data.`,
    { model: m.model, effort: m.effort }
  )
}

// ---- schemas -------------------------------------------------------------
const CONFIG_SCHEMA = {
  type: 'object',
  properties: {
    mission: { type: 'string' },
    roster: {
      type: 'object',
      properties: {
        lead: { type: 'string' },
        specialists: { type: 'array', items: { type: 'string' } },
        test: { type: 'string' },
      },
      required: ['lead', 'test'],
    },
    ownership: { type: 'array', items: { type: 'string' } },
    routing: { type: 'object', description: 'stage-class → {model, effort}; global defaults with team overrides merged (team wins); plus a "fallback" key: the {model, effort} a failed stage retries on' },
    pack: { type: 'string', description: 'full context-pack markdown' },
    memory: { type: 'string', description: 'full team-lessons markdown ("" if absent)' },
    orgMemory: { type: 'string', description: 'concatenated org-memory markdown ("" if absent)' },
  },
  required: ['mission', 'roster', 'ownership', 'routing', 'pack'],
}

const PLAN_SCHEMA = {
  type: 'object',
  properties: {
    feasible: { type: 'boolean' },
    questions: { type: 'array', items: { type: 'string' }, description: 'when infeasible: what the brief must answer' },
    packages: {
      type: 'array',
      description: 'required when feasible=true; empty when feasible=false',
      items: {
        type: 'object',
        properties: {
          title: { type: 'string' },
          files: { type: 'array', items: { type: 'string' } },
          instructions: { type: 'string' },
          agentType: { type: 'string', description: 'roster agent best suited; empty = team lead' },
        },
        required: ['title', 'files', 'instructions'],
      },
    },
    testPlan: { type: 'string', description: 'required when feasible=true; "" when feasible=false' },
    docTargets: { type: 'array', items: { type: 'string' } },
    risks: { type: 'array', items: { type: 'string' } },
    lessons: { type: 'array', items: { type: 'string' } },
    orgLessons: { type: 'array', items: { type: 'string' }, description: 'durable CROSS-TEAM facts/decisions (rare; usually empty)' },
  },
  // ONLY `feasible` is unconditionally required. Requiring packages+testPlan made
  // {feasible:false, questions:[...]} schema-INVALID, so a lead exercising the cheap-failure
  // escape hatch could be retried to the cap and surface as a hard block — discarding the
  // questions it wanted to ask. The conditional shape is enforced in the decompose prompt,
  // and the runner re-checks it before it touches plan.packages.
  required: ['feasible'],
}

const BUILD_SCHEMA = {
  type: 'object',
  properties: {
    pr: { type: 'string', description: 'PR number (digits) — only the branch-creating package sets this; others return ""' },
    branch: { type: 'string' },
    summary: { type: 'string' },
    testsRun: { type: 'string' },
    touchedSource: { type: 'boolean', description: 'true if this change touched anything a reviewer must re-bless: non-test source, or an existing test assertion. false ONLY for review-neutral work (CI config, formatting, lockfiles, purely additive tests). When in doubt, true.' },
    outOfZoneNeeds: { type: 'array', items: { type: 'string' } },
    lessons: { type: 'array', items: { type: 'string' } },
    orgLessons: { type: 'array', items: { type: 'string' }, description: 'durable CROSS-TEAM facts/decisions (rare; usually empty)' },
  },
  required: ['summary'],
}

const DOCS_SCHEMA = {
  type: 'object',
  properties: {
    updated: { type: 'array', items: { type: 'string' } },
    noneNeeded: { type: 'boolean' },
    summary: { type: 'string' },
    bloatFlags: { type: 'array', items: { type: 'string' } },
    lessons: { type: 'array', items: { type: 'string' } },
    orgLessons: { type: 'array', items: { type: 'string' }, description: 'durable CROSS-TEAM facts/decisions (rare; usually empty)' },
  },
  required: ['summary'],
}

const REVIEW_SCHEMA = {
  type: 'object',
  properties: {
    verdict: { type: 'string', enum: ['approve', 'request-changes'] },
    securityOrCorrectnessOk: { type: 'boolean' },
    mustFix: { type: 'array', items: { type: 'string' } },
    nits: { type: 'array', items: { type: 'string' } },
    // Round >=2 only (optional, so an approving round-1 review stays schema-valid):
    // the per-item verdict on the PREVIOUS round's must-fix list. Makes convergence
    // measurable in telemetry instead of inferable from findings that never repeat.
    resolvedPriorItems: {
      type: 'array',
      description: 'one entry per prior-round must-fix item: was it actually resolved on this branch?',
      items: {
        type: 'object',
        properties: {
          item: { type: 'string' },
          resolved: { type: 'boolean' },
          note: { type: 'string' },
        },
        required: ['item', 'resolved'],
      },
    },
    lessons: { type: 'array', items: { type: 'string' } },
    orgLessons: { type: 'array', items: { type: 'string' }, description: 'durable CROSS-TEAM facts/decisions (rare; usually empty)' },
  },
  required: ['verdict', 'mustFix'],
}

const CI_SCHEMA = {
  type: 'object',
  properties: {
    green: { type: 'boolean' },
    failing: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          check: { type: 'string' },
          reason: { type: 'string' },
          // The CI agent already diagnoses these correctly — it just had nowhere structured
          // to say so, and free-text `reason` is read by nothing. OPTIONAL on purpose: an
          // omitted flag reads as false and routes to the code fixer (the old behaviour), so
          // an unfilled field costs a round rather than skipping a real defect.
          infra: {
            type: 'boolean',
            description: 'true = this failure has NO code cause (runner capacity/queue/quota, job never acquired, image-pull or network error, provider outage). false for anything that ran your code: test, lint, type, build failures. When in doubt: false.',
          },
        },
        required: ['check', 'reason'],
      },
    },
  },
  required: ['green', 'failing'],
}

// ---- Setup: resolve team config -----------------------------------------
phase('Setup')
let cfg = A.config || null
if (!cfg) {
  cfg = await withRetry(
    'setup:config',
    'Setup',
    (retry) => `Resolve the team configuration for team "${A.team}" in this repo.${retry ? ' (Previous attempt returned nothing — read the files carefully and return the full structured object.)' : ''}

Read these repo files:
1. .claude/teams/${A.team}.yaml — the team definition
2. .claude/teams/model-routing.yaml — global stage-class routing defaults
3. The context-pack file named by the team yaml's context_pack field (path relative to .claude/teams/)
4. .claude/teams/memory/${A.team}.md (if missing, use "")
5. .claude/org-memory/decisions.md + architecture.md + lessons.md (concatenate in that order; if the directory is absent, use "")

Return: mission, roster, ownership from the team yaml; routing = the global defaults with the team yaml's routing overrides merged on top (team override wins per stage class), PLUS the routing file's top-level "fallback" entry carried through under the key "fallback" (a team routing.fallback override wins); pack = the FULL context-pack markdown; memory = the FULL memory markdown; orgMemory = the concatenated org-memory markdown ("" if absent).`,
    { model: 'haiku', effort: 'low', schema: CONFIG_SCHEMA }
  )
  if (!cfg) return await blocked('setup', 'could not resolve team config from .claude/teams/')
}
// Conservative fallback if a stage class is missing from routing — never silently cheap.
// Distinct from cfg.routing.fallback (fallbackRoute above), which is where a stage that
// FAILED escalates on retry; this one covers a routing key that was never configured.
const r = (stageClass) => (cfg.routing && cfg.routing[stageClass]) || { model: 'opus', effort: 'medium' }

// ---- Shared guardrails (injected into every mutating stage prompt) -------
// Project-specific commands (formatter, linter, type-checker, test prefix) come
// from the team's context pack — keep this block tool-agnostic.
const GUARDRAILS = `
NON-NEGOTIABLE CONSTRAINTS:
- Work in your isolated worktree. FIRST run \`git fetch origin\`. The run branch is \`${BRANCH}\`: create it from origin/<default-branch> if it doesn't exist yet, otherwise check it out and pull its latest.
- Stay inside this team's ownership zones: ${cfg.ownership.join(', ')} — plus tests/ and docs/. If the task needs edits outside these zones, DO NOT make them; list them under outOfZoneNeeds in your report instead (the dispatcher arbitrates cross-zone work).
- Run the project's formatter, linter, and type-checker clean on changed files (the exact commands are in the team context pack). If a shared local test resource throws transient errors under parallel agents, rerun the targeted slice before treating it as a real failure.
- Commit convention: {type}({scope}): {description} matching the ticket type. Do NOT add any AI/agent co-authorship trailer to commits.
- DO NOT MERGE. DO NOT push to the default branch. The PR stays open for human approval.
- DO NOT execute stateful/outward operations (production DB writes, object-store pushes, queue drains, backfills, deploys). Document them as ops steps in the PR body instead.
- If you learn something durable a future ${A.team}-team run should know, put it in your "lessons" report field (one line each).
- If you learn something durable that affects OTHER teams too (an org-wide decision, contract, or invariant), put it in your "orgLessons" report field instead (one line each; rare — most runs report none).
- REPORT FORMAT: every string field in your final structured report must be SHORT and SINGLE-LINE (≤300 chars, no newlines, no backticks, minimal quotes) — long multiline strings break the report parser and fail the whole stage. Put detail in the PR body / commit messages, never in the report.

## Team context pack (${A.team})
${cfg.pack}
${cfg.memory ? `\n## Team lessons\n${cfg.memory}` : ''}`

// ---- Decompose -----------------------------------------------------------
phase('Decompose')
const dr = r('decompose')
const plan = await withRetry(
  'decompose',
  'Decompose',
  (retry) => `You are the ${A.team} team lead decomposing ticket **${A.ticket}** into work packages.${retry ? ' (Previous attempt returned nothing — produce the full structured plan.)' : ''}

## Ticket brief
${A.brief}

## Team mission
${cfg.mission}

READ-ONLY stage: explore the repo but DO NOT edit files or create branches.

Produce:
- packages: ordered, NON-OVERLAPPING file sets, each sized for one agent in one sitting; for each: title, files, concrete instructions, and agentType (choose from the roster: lead ${cfg.roster.lead}, specialists ${(cfg.roster.specialists || []).join(', ') || 'none'}). Fewer, coherent packages beat many fragments — most tickets need exactly one.
- testPlan: what the test role (${cfg.roster.test}) should cover, including a tests/regression/ pin if this is a high-severity bug.
- docTargets: repo docs this change likely invalidates (empty list is fine).
- risks: what could silently break (the team pack's trip-wires are your checklist).

If the brief is too vague or infeasible to implement safely, return feasible=false with concrete questions — that is a GOOD outcome (cheap failure beats wasted downstream tokens).

REPORT SHAPE: always set feasible. When feasible=true, packages and testPlan are REQUIRED — a plan without them is unusable and fails the stage. When feasible=false, put your questions in questions and return packages=[] and testPlan="" — never invent packages for a brief you cannot safely implement.

## Team context pack (${A.team})
${cfg.pack}
${cfg.memory ? `\n## Team lessons\n${cfg.memory}` : ''}
${cfg.orgMemory ? `\n## Org memory (cross-team)\n${cfg.orgMemory}` : ''}`,
  { model: dr.model, effort: dr.effort, agentType: cfg.roster.lead, schema: PLAN_SCHEMA }
)
if (!plan) return await blocked('decompose')
if (!plan.feasible) {
  log(`team-run ${A.runId}: ill-specified — decompose returned questions instead of packages`)
  await persist('ill-specified', { stage: 'decompose' })
  return {
    runId: A.runId, team: A.team, ticket: A.ticket, status: 'ill-specified',
    questions: plan.questions || [], trace: DRY ? trace : undefined,
    note: 'brief needs refinement before any build tokens are spent',
  }
}
// feasible=true no longer implies a usable plan (the schema's hard requirement is `feasible`
// alone so the ill-specified path stays reachable), so check the shape here rather than
// crashing on plan.packages.length.
if (!Array.isArray(plan.packages) || !plan.packages.length || !plan.testPlan) {
  return await blocked('decompose', 'decompose returned feasible=true without work packages or a test plan')
}

// ---- Build: implement packages sequentially, then tests, then docs -------
// Sequential on ONE branch is deliberate: parallel packages on a shared branch
// race on push. The throughput win comes from parallel team-runs, not
// intra-run parallelism. Revisit after /model-eval telemetry accrues.
phase('Build')
const ir = r('implement')
for (let i = 0; i < plan.packages.length; i++) {
  const p = plan.packages[i]
  const first = i === 0
  const res = await withRetry(
    `implement:${i + 1}`,
    'Build',
    (retry) => `Implement work package ${i + 1}/${plan.packages.length} for **${A.ticket}** (${A.team} team-run).${retry ? '\n(Previous attempt failed to report. Redo IDEMPOTENTLY: first check what is already committed on the branch, then complete the remainder.)' : ''}

## Ticket brief
${A.brief}

## This package: ${p.title}
Files in scope: ${p.files.join(', ')}
${p.instructions}
${plan.risks && plan.risks.length ? `\n## Known risks (from decompose)\n${plan.risks.map((x) => `- ${x}`).join('\n')}` : ''}

${first
  ? `You are the FIRST package: create branch \`${BRANCH}\` off the default branch, implement, commit, push, then open a DRAFT PR (\`gh pr create --draft\`) titled "${A.ticket.toLowerCase()}: <short description>" with a body summarizing the run. REPORT the PR number in the pr field.`
  : `The branch \`${BRANCH}\` and its draft PR already exist: check out the branch, pull latest, implement, commit, push to the SAME branch. Report pr="".`}
${GUARDRAILS}`,
    { agentType: p.agentType || cfg.roster.lead, isolation: 'worktree', model: ir.model, effort: ir.effort, schema: BUILD_SCHEMA }
  )
  if (!res) return await blocked(`implement:${i + 1}`)
  if (first) pr = String(res.pr || '').replace(/\D/g, '')
}
if (!pr) return await blocked('implement:1', 'first package reported no PR number')

const tr = r('write-tests')
const testRes = await withRetry(
  'test',
  'Build',
  (retry) => `You are ${cfg.roster.test} adding tests for **${A.ticket}** on branch \`${BRANCH}\` (draft PR #${pr}).${retry ? '\n(Previous attempt failed to report. Redo idempotently: check which tests already exist on the branch first.)' : ''}

## Test plan (from the team lead's decompose)
${plan.testPlan}

Check out the branch, pull latest, write/extend the tests, run the targeted slice to prove they pass, commit, push to the SAME branch. If this ticket is a high-severity bug, include a regression pin under tests/regression/ (test_<ticket>_<short>) that pins the BUG, not just the fix.
${GUARDRAILS}`,
  { agentType: cfg.roster.test, isolation: 'worktree', model: tr.model, effort: tr.effort, schema: BUILD_SCHEMA }
)
if (!testRes) return await blocked('test')

const dcr = r('docs-author')
const docsRes = await withRetry(
  'docs',
  'Build',
  (retry) => `You are the docs-author for **${A.ticket}** on branch \`${BRANCH}\` (draft PR #${pr}).${retry ? '\n(Previous attempt failed to report. Redo idempotently.)' : ''}

Check out the branch, pull latest, then run \`git diff origin/<default-branch>...HEAD --stat\` to see what this run changed.
Doc targets flagged by decompose: ${plan.docTargets && plan.docTargets.length ? plan.docTargets.join(', ') : '(none flagged — rely on your diff scan)'}
Update ONLY repo docs the diff invalidates (README sections, docs/, runbook files, user-facing module docs). Never document aspirationally. If genuinely nothing is invalidated, commit nothing and return noneNeeded=true. Commit + push any updates to the SAME branch. Flag (don't fix) any docs bloat you notice in bloatFlags.
${GUARDRAILS}`,
  { agentType: 'docs-author', isolation: 'worktree', model: dcr.model, effort: dcr.effort, schema: DOCS_SCHEMA }
)
if (!docsRes) return await blocked('docs')

// ---- Gates: review + CI, each with its OWN bounded budget ---------------
// The two gates are independent, so the loop re-enters at the gate that failed
// instead of restarting at review. A mechanical CI fix no longer costs a review
// round — which mattered because a review round is a full audit, not a re-check.
phase('Gates')
const rr = r('review')
const fr = r('revision-fix')
const mr = r('mechanical')
const history = []
let gate = 'review'   // which gate the loop (re-)enters next
let gateSteps = 0     // total gate iterations, review + CI (the overall ceiling)
let reviewRounds = 0
let ciAttempts = 0
let ciInfraReruns = 0 // infra-only CI reds re-run without spending a gate round (bounded)
let reviewOk = false
let ciOk = false
let clean = false
// unverified*: a fix has been pushed to the branch that THIS gate has not looked at
// since. It is the difference between "we checked HEAD" and "we are guessing".
let unverifiedReview = false
let unverifiedCi = false
let outstanding = []  // the must-fix list the most recent revision was told to address

// Prior review rounds are RENDERED INTO the next review prompt. Without this, `history`
// only ever reached telemetry, so every round was a fresh unbounded audit whose findings
// were disjoint from the previous round's and the loop could not converge.
const priorReviewBlock = () => {
  const prior = history.filter((h) => h.gate === 'review' && h.items.length)
  if (!prior.length) return ''
  return `
## Prior review rounds on THIS PR — read this BEFORE you look at the diff
${prior.map((h) => `Round ${h.round} must-fix:\n${h.items.map((x, i) => `  ${i + 1}. ${x}`).join('\n')}`).join('\n')}

You are RE-REVIEWING the revisions pushed in response to the findings above. This is a
convergence pass, not a fresh audit:
1. VERIFY every prior must-fix item above against the current branch, and report each one in resolvedPriorItems as {item, resolved, note}. An item you find still unresolved is the ONLY finding you may repeat in mustFix.
2. A finding you are raising for the FIRST TIME belongs in mustFix ONLY if it is a correctness, security, or data-integrity regression introduced by the revision commits themselves (diff the commits added since the previous round). Everything else you are noticing for the first time now — documentation, consistency, naming, style, test-shape preference — goes in nits, NOT mustFix.
3. Do not open new lines of inquiry into code an earlier round already read and did not flag. If every prior item is resolved and the revision commits introduce no new regression, APPROVE.
`
}

// Reused verbatim by the post-loop CI confirm pass, so the two cannot drift.
const CI_PROMPT = `Verify CI on **PR #${pr}**. Run \`gh pr checks ${pr} --watch --interval 20\` and wait for ALL checks to conclude — this gate catches what local slices miss (full test suite, custom lints, type-check). Report green=true only if every non-skipped check passed. If any failed, name EACH failing check with a one-line reason from \`gh run view <run-id> --log-failed\`. Do not fix anything. green=false with an empty failing list is not allowed.

For EACH failing check also set infra: true when the failure has NO code cause — the job was never acquired by a runner, runner capacity/queue/quota, an image-pull or network error, a provider-side outage, or a cancelled/timed-out job that never executed the build. Set infra: false for anything that actually ran this branch's code: test failures, lint, type errors, build errors. When in doubt, false. This field is READ BY THE RUNNER: an all-infra red is re-run instead of being handed to a code fixer, so a wrong true wastes CI and a wrong false wastes a fix round.`

while (!clean && gateSteps < MAX_GATE_ROUNDS) {
  if (gate === 'review') {
    if (reviewRounds >= MAX_REVIEW_ROUNDS) break
    gateSteps++
    reviewRounds++
    const review = await call(
      `review#${reviewRounds}`,
      'Gates',
      `Code-review **PR #${pr}** (branch \`${BRANCH}\`) for ${A.ticket}. First mark it ready for review (\`gh pr ready ${pr}\`), then check out the branch in your worktree.

Task intent:
${A.brief}

Focus on CORRECTNESS and SECURITY over style: does the change do what the ticket needs without introducing a regression, a silent-failure path, a security/authorization leak, or data corruption? This PR also contains test and docs commits — verify the tests actually pin the behavior and the doc changes match the code (stale docs are a must-fix). Run static analysis and the relevant tests; verify any "pre-existing failure" claim against the default branch rather than trusting it. Post a structured PR review, but the LOAD-BEARING output is your structured return: verdict (approve | request-changes) and a concrete mustFix list (empty when approving). Be strict — a plausible-but-wrong change must die here. Do NOT merge.
${priorReviewBlock()}
## Team context pack (${A.team})
${cfg.pack}
${cfg.orgMemory ? `\n## Org memory (cross-team)\n${cfg.orgMemory}` : ''}`,
      { agentType: 'code-reviewer', model: rr.model, effort: rr.effort, schema: REVIEW_SCHEMA }
    )
    if (review) unverifiedReview = false
    if (!review || review.verdict === 'request-changes') {
      const mustFix = review && review.mustFix && review.mustFix.length
        ? review.mustFix
        : ['(reviewer returned no findings — re-inspect the full diff against the brief)']
      history.push({
        round: reviewRounds, gate: 'review', items: mustFix,
        ...(review && review.resolvedPriorItems ? { resolvedPrior: review.resolvedPriorItems } : {}),
      })
      reviewOk = false
      outstanding = mustFix
      await call(
        `revise#${reviewRounds}`,
        'Gates',
        `Revise PR #${pr} for **${A.ticket}** — code review requested changes. Check out branch \`${BRANCH}\`, pull latest, address EVERY must-fix item below, push to the SAME branch.

## Must-fix items
${mustFix.map((m, i) => `${i + 1}. ${m}`).join('\n')}
${GUARDRAILS}`,
        { agentType: cfg.roster.lead, isolation: 'worktree', model: fr.model, effort: fr.effort, schema: BUILD_SCHEMA }
      )
      // The revision moved the branch: neither gate's last verdict describes HEAD.
      unverifiedReview = true
      unverifiedCi = true
      ciOk = false
      continue
    }
    reviewOk = true
    outstanding = []
    gate = 'ci'
    continue
  }

  if (ciAttempts >= MAX_CI_ATTEMPTS) break
  gateSteps++
  ciAttempts++
  const ci = await call(`ci#${ciAttempts}`, 'Gates', CI_PROMPT, { model: mr.model, effort: mr.effort, schema: CI_SCHEMA })
  if (ci) unverifiedCi = false
  if (!ci || !ci.green) {
    const failing = ci && ci.failing && ci.failing.length
      ? ci.failing
      : [{ check: 'unknown', reason: 'CI verify agent returned no detail' }]
    // A red whose every failing check is INFRASTRUCTURE has no code cause. Dispatching a
    // fixer at it burns tokens on a defect that does not exist AND spends a gate round the
    // run needs for real findings (one production run reached stalemate that way, with two
    // legitimate correctness bugs still unaddressed). Re-run the jobs and refund the round.
    const allInfra = !!ci && failing.every((f) => f.infra === true)
    history.push({ round: ciAttempts, gate: 'ci', ...(allInfra ? { infra: true } : {}), items: failing })
    ciOk = false
    if (allInfra && ciInfraReruns < MAX_CI_INFRA_RERUNS) {
      ciInfraReruns++
      // Refund both counters — this iteration is not a gate round. MAX_CI_INFRA_RERUNS is
      // what bounds the refund, so the loop still terminates in at most
      // MAX_GATE_ROUNDS + MAX_CI_INFRA_RERUNS iterations.
      gateSteps--
      ciAttempts--
      await call(
        `ci-rerun#${ciInfraReruns}`,
        'Gates',
        `CI is red on PR #${pr} for **${A.ticket}**, and EVERY failing check is an infrastructure failure with no code cause:
${failing.map((f) => `- ${f.check}: ${f.reason}`).join('\n')}

Re-run only the failed jobs: \`gh run list --branch ${BRANCH} --limit 10\` to find them, then \`gh run rerun <run-id> --failed\` for each failed run. Do NOT change any code, do not commit, do not push, do not merge. Report one line naming what you re-ran (or that nothing could be re-run).`,
        { model: mr.model, effort: mr.effort }
      )
      unverifiedCi = true
      continue
    }
    if (ciAttempts >= MAX_CI_ATTEMPTS) break
    // The specialist fixes CI first; if it goes red AGAIN, debug-expert gets one
    // root-cause pass; a third red blocks the run.
    const fixer = ciAttempts === 1 ? cfg.roster.lead : 'debug-expert'
    const ciFix = await call(
      `ci-fix#${ciAttempts}`,
      'Gates',
      `CI is RED on PR #${pr} for **${A.ticket}** (attempt ${ciAttempts}).${fixer === 'debug-expert' ? ' A previous fix attempt did not clear it — ROOT-CAUSE the failure before touching code; do not shotgun.' : ''} Check out branch \`${BRANCH}\`, pull latest, fix the failing checks, push to the SAME branch.

## Failing checks
${failing.map((f) => `- ${f.check}: ${f.reason}`).join('\n')}

For each failure decide: real regression in this change, or a test/lint that must be updated for intended new behavior? NEVER weaken a test to hide a real bug.
Report touchedSource=true if you changed non-test source OR altered an existing test's assertions (the code review gate must then re-run). Report false ONLY for review-neutral work — CI config, formatting, lockfiles, purely additive tests. When in doubt, report true.
${GUARDRAILS}`,
      { agentType: fixer, isolation: 'worktree', model: fr.model, effort: fr.effort, schema: BUILD_SCHEMA }
    )
    unverifiedCi = true
    // DECISION (D4): after a CI-only fix, does the review gate re-run?
    // Ruling: yes, UNLESS the fixer reports touchedSource === false. Skipping review
    // unconditionally is unsafe — this stage is explicitly permitted to edit tests, and
    // a test weakened under CI pressure is exactly the failure the review gate exists to
    // catch; re-running it unconditionally is what D4 is about (it re-opens a full audit
    // over a change that may be a lockfile bump). The reported signal splits the two, and
    // it fails SAFE: anything other than an explicit false — a missing field, an unparsed
    // report, a null return — routes back through review.
    const reviewNeutral = !!(ciFix && ciFix.touchedSource === false)
    gate = reviewNeutral ? 'ci' : 'review'
    if (!reviewNeutral) {
      reviewOk = false
      unverifiedReview = true
    }
    continue
  }
  ciOk = true
  clean = reviewOk && ciOk
  if (!clean) gate = 'review'
}

// The loop can exit immediately after a fix that nothing has looked at, in which case the
// terminal status describes the tree BEFORE that fix (one production run was reported
// review-stalemate and then merged unchanged by a human — revise#3 had already fixed it).
// Spend at most one CONFIRM-ONLY pass per gate, scoped strictly to the outstanding items,
// so the reported status describes branch HEAD. Confirm passes never open new inquiry.
if (!clean && unverifiedReview && outstanding.length) {
  const confirm = await call(
    'review:confirm',
    'Gates',
    `CONFIRM-ONLY re-check of **PR #${pr}** (branch \`${BRANCH}\`) for ${A.ticket}. The review-round budget is spent and a revision addressing the items below was pushed but never verified. Check out the branch and pull latest.

## Outstanding must-fix items
${outstanding.map((m, i) => `${i + 1}. ${m}`).join('\n')}

Your ONLY question is whether each item above is resolved at the current branch HEAD. Report every item in resolvedPriorItems as {item, resolved, note}, the note citing the code that resolves it. Return verdict=approve if and only if EVERY item is resolved; otherwise request-changes listing ONLY the still-unresolved items in mustFix. Do NOT open any new line of inquiry, do not review code these items do not touch, and do not add new findings — anything else you notice goes in nits or nowhere. Do not push commits and do not merge.`,
    { agentType: 'code-reviewer', model: rr.model, effort: rr.effort, schema: REVIEW_SCHEMA }
  )
  if (confirm) {
    unverifiedReview = false
    reviewOk = confirm.verdict === 'approve'
    history.push({
      round: reviewRounds, gate: 'review', confirm: true,
      items: reviewOk ? [] : confirm.mustFix && confirm.mustFix.length ? confirm.mustFix : outstanding,
      ...(confirm.resolvedPriorItems ? { resolvedPrior: confirm.resolvedPriorItems } : {}),
    })
  }
}
// A confirm-only REVIEW may never promote a run whose CI was not verified green: clearing
// the review side at HEAD buys exactly one CI check, and only when a fix landed after the
// last one. If that check is red or does not report, the run does not reach pr-ready.
if (!clean && reviewOk && !ciOk && unverifiedCi) {
  const ciConfirm = await call('ci:confirm', 'Gates', CI_PROMPT, { model: mr.model, effort: mr.effort, schema: CI_SCHEMA })
  if (ciConfirm) {
    unverifiedCi = false
    ciOk = !!ciConfirm.green
    if (!ciOk) {
      history.push({
        round: ciAttempts, gate: 'ci', confirm: true,
        items: ciConfirm.failing && ciConfirm.failing.length ? ciConfirm.failing : [{ check: 'unknown', reason: 'CI confirm returned no detail' }],
      })
    }
  }
}
clean = reviewOk && ciOk

// Terminal status comes from the last gate round that actually FAILED (a clearing confirm
// pass records an empty item list). verifiedAtHead says whether the gate that decided this
// status looked at the current HEAD, or whether the run bounded out and this is a guess.
const failedRounds = history.filter((h) => h.items.length)
const lastGate = failedRounds.length ? failedRounds[failedRounds.length - 1].gate : null
const status = clean ? 'pr-ready' : !reviewOk && lastGate === 'review' ? 'review-stalemate' : 'needs-human'
const verifiedAtHead = clean ? true : !reviewOk ? !unverifiedReview : !unverifiedCi

// ---- Report: telemetry + state writes (skipped in dry-run) ---------------
phase('Report')
// The state-writer's OWN token cost cannot appear inside the record it writes: the record
// has to be serialized before that stage runs, and a second call to patch the file afterwards
// would itself be an unrecorded stage — the regress does not terminate. It is made
// RECOVERABLE instead: tokensBeforeReport is total run spend at serialization time, so the
// writer's cost is <the host's total run spend> - tokensBeforeReport. The object this
// workflow RETURNS does list it, because `stages` is the live array the writer appends to.
const tokensBeforeReport = DRY ? 0 : budget.spent()
const telemetry = {
  runId: A.runId, team: A.team, ticket: A.ticket, size: A.size || 'medium',
  runnerVersion: RUNNER_VERSION,
  // `rounds` stays the REVIEW-round count so pre-0.2.0 analysis keeps reading what it
  // always read (the old single loop incremented once per review call); the CI budget
  // and the combined step count are reported alongside it.
  timestamp: A.timestamp, branch: BRANCH, pr, status, rounds: reviewRounds,
  ciAttempts, ciInfraReruns, gateSteps, tokensBeforeReport, verifiedAtHead, stages, history,
}
let stateNote
if (!DRY) {
  // Emit the ACTUAL terminal status. Collapsing four distinct outcomes into 'blocked'
  // made every convergence question unanswerable from events.jsonl.
  const eventType = status === 'pr-ready' ? 'pr_opened' : status
  const stateRes = await withRetry(
    'report:state',
    'Report',
    (retry) => `Persist team-run state.${retry ? ' (Previous attempt failed — redo idempotently; steps may be partially applied.)' : ''} Work in the MAIN repo checkout (run \`git rev-parse --show-toplevel\` from your CWD; use absolute paths — do NOT cd into any worktree). All paths are under <repo>/.claude/teams/state/ — create dirs if missing (mkdir -p state/runs), and seed board.json with {"runs":[]} if absent.

1. Write EXACTLY this JSON to state/runs/${A.runId}.json:
${JSON.stringify(telemetry)}

2. Append EXACTLY this line to state/events.jsonl:
${JSON.stringify({ ts: A.timestamp, run: A.runId, team: A.team, type: eventType, ticket: A.ticket, pr })}

3. Update state/board.json with jq: find .runs[] entry with .id=="${A.runId}" and set .status="${status}", .pr="${pr}", .branch="${BRANCH}"; if no entry exists, append {"id":"${A.runId}","team":"${A.team}","ticket":"${A.ticket}","status":"${status}","branch":"${BRANCH}","pr":"${pr}","worktree":"","ts":"${A.timestamp}"}.

${lessons.length
  ? `4. Append to .claude/teams/memory/${A.team}.md:\n\n## ${A.timestamp} ${A.ticket}\n${lessons.map((l) => `- (${l.stage}) ${l.lesson}`).join('\n')}\n\nNOTE: the memory file IS tracked by git but do NOT commit it here — memory commits ride the next framework PR.`
  : '4. No lessons this run — do not touch the memory file.'}

${orgLessons.length
  ? `5. Append to .claude/org-memory/lessons.md, directly under the "## Candidates (pending curation)" heading (if the file or heading is missing, skip this step and say so):\n${orgLessons.map((l) => `- [ ] (${A.runId}) (${l.stage}) ${l.lesson}`).join('\n')}\n\nNOTE: org-memory files are tracked by git but do NOT commit them — curation commits are human.`
  : '5. No org-lesson candidates this run — do not touch .claude/org-memory/.'}

Do not commit or push anything. State files under state/ are gitignored runtime data.`,
    { model: mr.model, effort: mr.effort }
  )
  if (!stateRes) stateNote = 'state persistence failed after retry — board/telemetry may be stale'
}

log(`team-run ${A.runId}: ${status}${pr ? ` — PR #${pr}` : ''} after ${gateSteps} gate round(s) (${reviewRounds} review / ${ciAttempts} CI${ciInfraReruns ? ` / ${ciInfraReruns} infra re-run` : ''})${verifiedAtHead ? '' : ' — status NOT verified at branch HEAD'}. Nothing merged.`)
return { ...telemetry, ...(stateNote ? { stateNote } : {}), trace: DRY ? trace : undefined, note: 'Nothing merged — PR awaits human approval.' }
