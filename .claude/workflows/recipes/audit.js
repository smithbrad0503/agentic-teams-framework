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
  (r) =>
    parallel(
      ((r && r.findings) || []).map((f) => () =>
        agent(
          `Adversarially verify this audit finding in ${A.target} — try to REFUTE it:\n${f.file}: ${f.issue} (${f.severity})\n\nREAD-ONLY. Return real=true only if the issue genuinely exists as described; when uncertain, real=false.`,
          { label: `verify:${f.file}`, phase: 'Verify', schema: VERDICT_SCHEMA }
        ).then((v) => ({ ...f, verified: !!(v && v.real), verifyReason: (v && v.reason) || '' }))
      )
    )
)
const confirmed = audited
  .filter(Boolean)
  .flat()
  .filter(Boolean)
  .filter((f) => f.verified)
log(`audit: ${confirmed.length} confirmed finding(s) on ${A.target}`)
return { timestamp: A.timestamp || '', target: A.target, confirmed }
