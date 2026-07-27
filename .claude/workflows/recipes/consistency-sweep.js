export const meta = {
  name: 'consistency-sweep',
  description: 'Sweep every surface of a repo against a locked contract — terminology, naming, product claims, deprecated APIs, brand voice — and verify each claimed violation in its own context.',
  phases: [
    { title: 'Sweep', detail: 'one read-only sweeper per surface: grep the forbidden terms first, then read for what grep cannot see' },
    { title: 'Verify', detail: 'each claimed violation re-checked in its surface and surrounding lines' },
  ],
}

// ---- args contract -------------------------------------------------------
// {
//   contractPath: 'docs/TERMINOLOGY.md',       // preferred — see note below
//   contract: 'the locked rules, inline',      // fallback when there is no file yet
//   surfaces: [{ key: 'user-strings', scope: 'locales/*.json — every value ships verbatim' }, …],
//   forbidden: ['Oldblood', 'LegacyFooClient'], // literal terms; the cheap high-recall pass
//   timestamp: '2026-01-01T10:30:00-05:00',    // dispatcher-generated (no Date in scripts)
// }
// Prefer contractPath over contract. An inlined contract is a SECOND COPY of the
// rules, and second copies drift: the project this recipe was harvested from keeps
// its locked canon inline in three workflow scripts plus a design doc, and pays the
// sync cost on every rename — its own README names two of the four places to update.
// A path keeps one source of truth and lets every agent read the version that is
// live right now rather than the version that was true when someone pasted it.
let A = args || {}
if (typeof A === 'string') {
  try {
    A = JSON.parse(A)
  } catch (e) {
    return { error: 'consistency-sweep: args arrived as an unparseable string — pass a JSON object' }
  }
}
if (!A.contractPath && !A.contract) {
  return { error: 'consistency-sweep: args.contractPath (preferred) or args.contract is required — there is nothing to sweep against without a locked contract' }
}

// The reusable ordering: most outward-facing surface first, most internal last.
// Callers override the list, but the shape of the checklist is the point — a sweep
// that skips a tier does not know it skipped it.
const DEFAULT_SURFACES = [
  { key: 'user-strings', scope: 'user-facing strings — i18n catalogs, UI copy, email and notification templates, error messages: every value reaches a person verbatim' },
  { key: 'data-content', scope: 'data and content files — seed data, fixtures, CMS exports, config registries: names, titles, descriptions, canned copy' },
  { key: 'code-literals', scope: 'string literals in source that look user-facing (they should be going through the string catalog anyway — a hard-coded literal that also breaks the contract is a double finding)' },
  { key: 'internal-docs', scope: 'internal docs, specs and READMEs — not public, but stale wording here re-infects everything written next' },
  { key: 'marketing', scope: 'outward-facing marketing, landing pages, store listings, release notes — the public voice, and where claims get made' },
]

const surfaces = Array.isArray(A.surfaces) && A.surfaces.length ? A.surfaces : DEFAULT_SURFACES
if (surfaces.some((s) => !s || !s.key || !s.scope)) {
  return { error: 'consistency-sweep: every args.surfaces entry needs {key, scope}' }
}
const forbidden = Array.isArray(A.forbidden) ? A.forbidden.filter((t) => typeof t === 'string' && t.trim()) : []

const VIOLATIONS_SCHEMA = {
  type: 'object',
  properties: {
    violations: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          file: { type: 'string' },
          where: { type: 'string', description: 'key / line number / section heading' },
          text: { type: 'string', description: 'the offending text, verbatim' },
          context: { type: 'string', description: 'the surrounding lines it sits in — without these a live UI string and a changelog entry about the old wording are the same string' },
          rule: { type: 'string', description: 'which contract rule it breaks' },
          suggested: { type: 'string', description: 'replacement text, if there is an obvious one' },
        },
        required: ['file', 'where', 'text', 'context', 'rule'],
      },
    },
  },
  required: ['violations'],
}
const VERDICT_SCHEMA = {
  type: 'object',
  properties: {
    holds: { type: 'boolean', description: 'true only if the text is really there AND really breaks the rule in THIS context' },
    exposure: { type: 'string', enum: ['public', 'internal'] },
    reason: { type: 'string', description: 'one line, ≤300 chars — cite the context that decided it' },
  },
  required: ['holds', 'exposure', 'reason'],
}

const CONTRACT = A.contractPath
  ? `The locked contract is the file ${A.contractPath} in this repo. READ IT FIRST and treat it as the only source of truth — ignore any copy of these rules quoted elsewhere, it may be stale.`
  : `Locked contract (verbatim):\n${A.contract}`

const GREP_STEP = forbidden.length
  ? `1) CHEAP PASS FIRST — grep this surface case-insensitively for each of these literal terms: ${forbidden.map((t) => JSON.stringify(t)).join(', ')}. High recall, near-zero cost. Every hit is a CANDIDATE, not yet a violation.`
  : `1) CHEAP PASS FIRST — grep this surface case-insensitively for every term the contract forbids by name. High recall, near-zero cost. Every hit is a CANDIDATE, not yet a violation.`

const sweepPrompt = (s) => `${CONTRACT}

Sweep ONE surface for contract violations — surface "${s.key}": ${s.scope}

${GREP_STEP}
2) THEN READ the surface. Grep cannot see a paraphrase, a renamed concept described in the old words, drifted tone, or a claim that is implied rather than stated. Those are violations too, and they are the ones only reading finds.

READ-ONLY: read, grep and list. Change NOTHING, rewrite nothing, open no PR — this recipe reports, it never fixes.
For each violation give the file, where (key / line / section), the offending text verbatim, the rule it breaks, and \`context\`: the surrounding lines, enough that someone who cannot open the file could tell a live user-facing string from a changelog entry describing the old wording. Zero violations is a valid, good result — do not invent violations.`

// The verifier is the whole reason this recipe is not `grep`. It is given the
// surface and the surrounding lines, never the matched string alone: the identical
// string is a violation in shipped copy and completely legitimate in a decision log.
// A verifier handed only `v.text` can only re-confirm that the string exists, which
// the sweeper already knew.
const verifyPrompt = (v, s) => `${CONTRACT}

Verify ONE claimed violation by opening the file yourself. Judge the CONTEXT, never the matched string on its own.

Surface: "${s.key}" — ${s.scope}
File: ${v.file}
Where: ${v.where}
Matched text: ${v.text}
Surrounding context as reported by the sweeper: ${v.context || '(none reported — read the file and establish the surrounding lines yourself before deciding)'}
Rule claimed broken: ${v.rule}

The SAME string is a violation on one surface and entirely legitimate on another. It does NOT hold when the surrounding lines show it is: a historical decision log or changelog recording what the old wording was, a migration guide telling readers what the term used to be, a test fixture pinning the old behaviour, or a rule that names the forbidden term in order to forbid it. It DOES hold when the surrounding lines show it is live text a reader will take at face value.

holds=true only if the text really is at that location AND really breaks the stated rule given its surrounding context. When the context is ambiguous, holds=false.
exposure='public' if this location reaches users or the outside world (shipped strings, rendered content, marketing, release notes); 'internal' if it is internal-only.
READ-ONLY: read the file, change NOTHING.`

const swept = await pipeline(
  surfaces,
  (s) =>
    agent(sweepPrompt(s), { label: `sweep:${s.key}`, phase: 'Sweep', schema: VIOLATIONS_SCHEMA }),
  (r, s) =>
    parallel(
      ((r && r.violations) || []).map((v) => () =>
        agent(verifyPrompt(v, s), {
          label: `verify:${s.key}:${String(v.file || '?').slice(0, 40)}`,
          phase: 'Verify',
          schema: VERDICT_SCHEMA,
        }).then((d) => ({
          // A verifier that DIED is not a verifier that cleared the text. Collapsing
          // both to "not a violation" makes a crashed agent report a clean sweep —
          // the finding disappears and the run looks better than the codebase is.
          // Same discipline as `audit`: confirmed | refuted | unverified, three states.
          ...v,
          surface: s.key,
          verdict: d ? (d.holds ? 'confirmed' : 'refuted') : 'unverified',
          // Unknown exposure fails toward public: a violation we could not place is
          // assumed to be the expensive kind until a human says otherwise.
          exposure: d ? (d.exposure === 'internal' ? 'internal' : 'public') : 'unknown',
          verifyReason: (d && d.reason) || 'verifier agent returned no report',
        }))
      )
    )
)
const violations = swept
  .filter(Boolean)
  .flat()
  // A thunk that threw resolves to null and would vanish here for the same reason,
  // so it is recovered as unverified rather than dropped.
  .map((v) => v || { file: '(unknown)', where: '(unknown)', text: '(violation lost — verifier thunk errored)', rule: '(unknown)', surface: '(unknown)', verdict: 'unverified', exposure: 'unknown', verifyReason: 'verifier agent errored' })

const confirmed = violations.filter((v) => v.verdict === 'confirmed')
const unverified = violations.filter((v) => v.verdict === 'unverified')
// The split is computed here rather than handed to a summarizing agent: a summarizer
// that quietly omits a row is one more way to lose a finding.
const fixBeforePublic = confirmed.filter((v) => v.exposure !== 'internal')
const internalHygiene = confirmed.filter((v) => v.exposure === 'internal')
// A sweep that lost a verifier cannot claim CLEAN — it does not know what it missed.
const verdict = unverified.length ? 'INCOMPLETE' : confirmed.length ? 'VIOLATIONS' : 'CLEAN'
log(`consistency-sweep: ${verdict} — ${fixBeforePublic.length} to fix before anything public, ${internalHygiene.length} internal hygiene${unverified.length ? `, ${unverified.length} UNVERIFIED (verifier failed — triage by hand, treat as public-facing until you have)` : ''}`)
return {
  timestamp: A.timestamp || '',
  contract: A.contractPath || 'inline',
  surfaces: surfaces.map((s) => s.key),
  verdict,
  fixBeforePublic,
  internalHygiene,
  unverified,
}
