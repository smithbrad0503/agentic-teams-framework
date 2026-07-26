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
//                mechanical, review, revision-fix, librarian.
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

// ---- args contract -------------------------------------------------------
// {
//   team: 'backend',                          // matches .claude/teams/<team>.yaml
//   ticket: 'TICKET-123',
//   brief: 'concrete task instructions',
//   size: 'small' | 'medium' | 'large',       // budget class (recorded in telemetry)
//   runId: 'backend-ticket-123-20260101T1030',// dispatcher-generated (no Date in scripts)
//   timestamp: '2026-01-01T10:30:00-05:00',   // dispatcher-generated
//   config?: { mission, roster, ownership, routing, pack, memory },  // injected by /team dispatch
//   maxRounds?: 3,
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
  stages.push({
    label,
    model: opts.model || 'inherit',
    effort: opts.effort || 'inherit',
    tokens: budget.spent() - before,
    ok: res != null,
    ...(err ? { error: err } : {}),
  })
  if (res && Array.isArray(res.lessons)) lessons.push(...res.lessons.map((l) => ({ stage: label, lesson: l })))
  if (res && Array.isArray(res.orgLessons)) orgLessons.push(...res.orgLessons.map((l) => ({ stage: label, lesson: l })))
  return res
}

// Failure policy: one retry with failure context; second failure → caller blocks.
const withRetry = async (label, phaseName, promptFn, opts) => {
  const first = await call(label, phaseName, promptFn(false), opts)
  if (first) return first
  return call(`${label}:retry`, phaseName, promptFn(true), opts)
}

const blocked = async (stage, note) => {
  await persist('blocked', { stage, pr: typeof pr !== 'undefined' ? pr : '' })
  return {
    runId: A.runId, team: A.team, ticket: A.ticket, status: 'blocked', stage,
    note: note || `stage ${stage} failed twice — needs human arbitration`,
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
    timestamp: A.timestamp, branch: BRANCH, pr: opts.pr || '', status: statusVal,
    stage: opts.stage || '', stages,
  }
  const evt = { ts: A.timestamp, run: A.runId, team: A.team, type: 'blocked', ticket: A.ticket, pr: opts.pr || '' }
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
    routing: { type: 'object', description: 'stage-class → {model, effort}; global defaults with team overrides merged (team wins)' },
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
    testPlan: { type: 'string' },
    docTargets: { type: 'array', items: { type: 'string' } },
    risks: { type: 'array', items: { type: 'string' } },
    lessons: { type: 'array', items: { type: 'string' } },
    orgLessons: { type: 'array', items: { type: 'string' }, description: 'durable CROSS-TEAM facts/decisions (rare; usually empty)' },
  },
  required: ['feasible', 'packages', 'testPlan'],
}

const BUILD_SCHEMA = {
  type: 'object',
  properties: {
    pr: { type: 'string', description: 'PR number (digits) — only the branch-creating package sets this; others return ""' },
    branch: { type: 'string' },
    summary: { type: 'string' },
    testsRun: { type: 'string' },
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
        properties: { check: { type: 'string' }, reason: { type: 'string' } },
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

Return: mission, roster, ownership from the team yaml; routing = the global defaults with the team yaml's routing overrides merged on top (team override wins per stage class); pack = the FULL context-pack markdown; memory = the FULL memory markdown; orgMemory = the concatenated org-memory markdown ("" if absent).`,
    { model: 'haiku', effort: 'low', schema: CONFIG_SCHEMA }
  )
  if (!cfg) return await blocked('setup', 'could not resolve team config from .claude/teams/')
}
// Conservative fallback if a stage class is missing from routing — never silently cheap.
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

// ---- Gates: review + CI, bounded revision loop --------------------------
phase('Gates')
const rr = r('review')
const fr = r('revision-fix')
const mr = r('mechanical')
const history = []
let round = 0
let ciAttempts = 0
let clean = false

while (round < MAX_ROUNDS && !clean) {
  round++
  const review = await call(
    `review#${round}`,
    'Gates',
    `Code-review **PR #${pr}** (branch \`${BRANCH}\`) for ${A.ticket}. First mark it ready for review (\`gh pr ready ${pr}\`), then check out the branch in your worktree.

Task intent:
${A.brief}

Focus on CORRECTNESS and SECURITY over style: does the change do what the ticket needs without introducing a regression, a silent-failure path, a security/authorization leak, or data corruption? This PR also contains test and docs commits — verify the tests actually pin the behavior and the doc changes match the code (stale docs are a must-fix). Run static analysis and the relevant tests; verify any "pre-existing failure" claim against the default branch rather than trusting it. Post a structured PR review, but the LOAD-BEARING output is your structured return: verdict (approve | request-changes) and a concrete mustFix list (empty when approving). Be strict — a plausible-but-wrong change must die here. Do NOT merge.

## Team context pack (${A.team})
${cfg.pack}
${cfg.orgMemory ? `\n## Org memory (cross-team)\n${cfg.orgMemory}` : ''}`,
    { agentType: 'code-reviewer', model: rr.model, effort: rr.effort, schema: REVIEW_SCHEMA }
  )
  if (!review || review.verdict === 'request-changes') {
    const mustFix = review && review.mustFix && review.mustFix.length
      ? review.mustFix
      : ['(reviewer returned no findings — re-inspect the full diff against the brief)']
    history.push({ round, gate: 'review', items: mustFix })
    await call(
      `revise#${round}`,
      'Gates',
      `Revise PR #${pr} for **${A.ticket}** — code review requested changes. Check out branch \`${BRANCH}\`, pull latest, address EVERY must-fix item below, push to the SAME branch.

## Must-fix items
${mustFix.map((m, i) => `${i + 1}. ${m}`).join('\n')}
${GUARDRAILS}`,
      { agentType: cfg.roster.lead, isolation: 'worktree', model: fr.model, effort: fr.effort, schema: BUILD_SCHEMA }
    )
    continue
  }

  const ci = await call(
    `ci#${round}`,
    'Gates',
    `Verify CI on **PR #${pr}**. Run \`gh pr checks ${pr} --watch --interval 20\` and wait for ALL checks to conclude — this gate catches what local slices miss (full test suite, custom lints, type-check). Report green=true only if every non-skipped check passed. If any failed, name EACH failing check with a one-line reason from \`gh run view <run-id> --log-failed\`. Do not fix anything. green=false with an empty failing list is not allowed.`,
    { model: mr.model, effort: mr.effort, schema: CI_SCHEMA }
  )
  if (!ci || !ci.green) {
    ciAttempts++
    const failing = ci && ci.failing && ci.failing.length
      ? ci.failing
      : [{ check: 'unknown', reason: 'CI verify agent returned no detail' }]
    history.push({ round, gate: 'ci', items: failing })
    if (ciAttempts >= 3) break
    // The specialist fixes CI first; if it goes red AGAIN, debug-expert gets one
    // root-cause pass; a third red blocks the run.
    const fixer = ciAttempts === 1 ? cfg.roster.lead : 'debug-expert'
    await call(
      `ci-fix#${round}`,
      'Gates',
      `CI is RED on PR #${pr} for **${A.ticket}** (attempt ${ciAttempts}).${fixer === 'debug-expert' ? ' A previous fix attempt did not clear it — ROOT-CAUSE the failure before touching code; do not shotgun.' : ''} Check out branch \`${BRANCH}\`, pull latest, fix the failing checks, push to the SAME branch.

## Failing checks
${failing.map((f) => `- ${f.check}: ${f.reason}`).join('\n')}

For each failure decide: real regression in this change, or a test/lint that must be updated for intended new behavior? NEVER weaken a test to hide a real bug.
${GUARDRAILS}`,
      { agentType: fixer, isolation: 'worktree', model: fr.model, effort: fr.effort, schema: BUILD_SCHEMA }
    )
    continue
  }
  clean = true
}

const lastGate = history.length ? history[history.length - 1].gate : null
const status = clean ? 'pr-ready' : lastGate === 'review' ? 'review-stalemate' : 'needs-human'

// ---- Report: telemetry + state writes (skipped in dry-run) ---------------
phase('Report')
const telemetry = {
  runId: A.runId, team: A.team, ticket: A.ticket, size: A.size || 'medium',
  timestamp: A.timestamp, branch: BRANCH, pr, status, rounds: round, stages, history,
}
let stateNote
if (!DRY) {
  const eventType = status === 'pr-ready' ? 'pr_opened' : 'blocked'
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

log(`team-run ${A.runId}: ${status}${pr ? ` — PR #${pr}` : ''} after ${round} gate round(s). Nothing merged.`)
return { ...telemetry, ...(stateNote ? { stateNote } : {}), trace: DRY ? trace : undefined, note: 'Nothing merged — PR awaits human approval.' }
