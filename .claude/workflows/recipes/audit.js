export const meta = {
  name: 'audit',
  description: 'Sweep a target area against a checklist with parallel read-only auditors, then adversarially verify findings.',
  phases: [
    { title: 'Audit', detail: 'one auditor per checklist item' },
    { title: 'Verify', detail: 'adversarial refutation of each finding' },
  ],
}

// ---- args contract -------------------------------------------------------
// {
//   target: 'src/auth/ (or a subsystem description)',
//   checklist: ['secrets in code', 'unvalidated input reaching queries', …],
//   timestamp: '2026-01-01T10:30:00-05:00',
// }
let A = args || {}
if (typeof A === 'string') {
  try {
    A = JSON.parse(A)
  } catch (e) {
    return { error: 'audit: args arrived as an unparseable string — pass a JSON object' }
  }
}
if (!A.target || !Array.isArray(A.checklist) || !A.checklist.length) {
  return { error: 'audit: args.target and a non-empty args.checklist are required' }
}

const FINDINGS_SCHEMA = {
  type: 'object',
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          file: { type: 'string' },
          issue: { type: 'string', description: 'one line, ≤300 chars' },
          severity: { type: 'string', enum: ['high', 'medium', 'low'] },
        },
        required: ['file', 'issue', 'severity'],
      },
    },
  },
  required: ['findings'],
}
const VERDICT_SCHEMA = {
  type: 'object',
  properties: {
    real: { type: 'boolean' },
    reason: { type: 'string', description: 'one line, ≤300 chars' },
  },
  required: ['real', 'reason'],
}

const audited = await pipeline(
  A.checklist,
  (item) =>
    agent(
      `Audit ${A.target} for: ${item}\n\nREAD-ONLY: inspect code and config, change NOTHING. Report concrete findings only (file, one-line issue, severity). Zero findings is a valid, good result — do not invent issues.`,
      { label: `audit:${String(item).slice(0, 40)}`, phase: 'Audit', schema: FINDINGS_SCHEMA }
    ),
  (r, item) =>
    // A dead stage-1 auditor returns NULL — it does not throw. `(r && r.findings) || []`
    // would turn that into an empty fan-out, an empty array, and a checklist item that
    // reads CLEAN because nobody looked. The outer recovery below cannot catch it: an
    // empty array IS an array. Only here, before the fan-out, can the two be told apart.
    !r || !Array.isArray(r.findings)
      ? [{
          file: '(unknown)',
          issue: `(checklist item never audited: "${item}")`,
          severity: 'unknown',
          verdict: 'unverified',
          verifyReason: 'the audit stage returned no report for this item',
        }]
      : parallel(
          r.findings.map((f) => () =>
        agent(
          `Adversarially verify this audit finding in ${A.target} — try to REFUTE it:\n${f.file}: ${f.issue} (${f.severity})\n\nREAD-ONLY. Return real=true only if the issue genuinely exists as described; when uncertain, real=false.`,
          { label: `verify:${f.file}`, phase: 'Verify', schema: VERDICT_SCHEMA }
        ).then((v) => ({
          // A verifier that DIED is not a verifier that refuted. Collapsing both to
          // false silently exonerates the finding — an audit that cannot check a
          // finding would report it as "not a real issue" and drop it. `health-check`
          // maps a dead agent to false too, but there false means "check failed",
          // which fails closed; here false means "no problem", which fails open.
          ...f,
          verdict: v ? (v.real ? 'confirmed' : 'refuted') : 'unverified',
          verifyReason: (v && v.reason) || 'verifier agent returned no report',
        }))
      )
    )
)
// Index-aligned at BOTH layers, and the outer one is the easy mistake.
// `pipeline` yields null for an item whose stage threw outright, so a
// `.filter(Boolean)` here silently deletes an ENTIRE checklist item — the audit
// then reports on fewer items than it was asked about, with nothing saying so.
// The inner recovery below only ever sees nulls *within* a surviving item's array,
// so it cannot cover this case no matter where it is placed.
const findings = audited
  .flatMap((r, i) =>
    Array.isArray(r)
      ? r
      : [{
          file: '(unknown)',
          issue: `(checklist item never assessed: "${A.checklist[i]}")`,
          severity: 'unknown',
          verdict: 'unverified',
          verifyReason: 'the verify stage errored for this entire checklist item',
        }]
  )
  // A verifier thunk that threw resolves to null inside a surviving item's array.
  .map((f) => f || { file: '(unknown)', issue: '(finding lost — verifier thunk errored)', severity: 'unknown', verdict: 'unverified', verifyReason: 'verifier agent errored' })
const confirmed = findings.filter((f) => f.verdict === 'confirmed')
const unverified = findings.filter((f) => f.verdict === 'unverified')
log(`audit: ${confirmed.length} confirmed finding(s) on ${A.target}${unverified.length ? `, ${unverified.length} UNVERIFIED (verifier failed — triage these by hand)` : ''}`)
// Shared recipe contract: every recipe returns `verdict`, and INCOMPLETE is reserved
// across all of them for "an agent died, so this is not a complete judgement". It is
// the one field a caller can check without knowing which recipe produced the result.
// INCOMPLETE outranks a clean result — a sweep that lost a verifier cannot claim CLEAN.
const verdict = unverified.length ? 'INCOMPLETE' : confirmed.length ? 'FINDINGS' : 'CLEAN'
return { timestamp: A.timestamp || '', target: A.target, verdict, confirmed, unverified }
