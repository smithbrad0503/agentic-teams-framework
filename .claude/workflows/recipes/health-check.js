export const meta = {
  name: 'health-check',
  description: 'Run a configured list of read-only health checks in parallel and return a red/green report.',
  phases: [{ title: 'Check', detail: 'one read-only agent per configured check' }],
}

// ---- args contract -------------------------------------------------------
// {
//   checks: [{ name: 'api-up', instructions: 'curl the /health endpoint …' }, …],
//   timestamp: '2026-01-01T10:30:00-05:00',   // dispatcher-generated (no Date in scripts)
// }
// Checks are project-specific: keep them in a cockpit note or a small
// .claude/workflows/health-checks.json the dispatcher reads and passes in.
let A = args || {}
if (typeof A === 'string') {
  try {
    A = JSON.parse(A)
  } catch (e) {
    return { error: 'health-check: args arrived as an unparseable string — pass a JSON object' }
  }
}
if (!Array.isArray(A.checks) || !A.checks.length) {
  return { error: 'health-check: args.checks must be a non-empty array of {name, instructions}' }
}

const CHECK_SCHEMA = {
  type: 'object',
  properties: {
    ok: { type: 'boolean' },
    detail: { type: 'string', description: 'one line of evidence (≤300 chars, single line)' },
  },
  required: ['ok', 'detail'],
}

phase('Check')
const results = await parallel(
  A.checks.map((c) => () =>
    agent(
      `Health check "${c.name}". READ-ONLY: run commands and read files to verify, but change NOTHING and deploy NOTHING.\n\n${c.instructions}\n\nReturn ok=true only if the check genuinely passes; detail = one line of evidence (≤300 chars, single line).`,
      { label: `check:${c.name}`, phase: 'Check', schema: CHECK_SCHEMA }
    ).then((r) => ({ name: c.name, ok: !!(r && r.ok), detail: (r && r.detail) || 'check agent returned no report' }))
  )
)
const settled = results.map((r, i) => r || { name: A.checks[i].name, ok: false, detail: 'check agent errored' })
const failing = settled.filter((r) => !r.ok)
log(`health-check: ${settled.length - failing.length}/${settled.length} green`)
return { timestamp: A.timestamp || '', green: failing.length === 0, results: settled, failing }
