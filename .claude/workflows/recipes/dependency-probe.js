export const meta = {
  name: 'dependency-probe',
  description:
    'Probe every third-party dependency a system relies on against the ways providers actually fail in production, then find the shared fate that would break several of them at once. Read-only — reports exposures, never fixes them.',
  phases: [
    { title: 'Probe', detail: 'one read-only prober per dependency, reconciled against every configured failure mode' },
    { title: 'Synthesize', detail: 'barrier over ALL probe results: which single change would break the most dependencies at once' },
  ],
}

// ---- args contract -------------------------------------------------------
// {
//   target: 'apps/web (repo root, or a subsystem description)',   // REQUIRED
//   dependencies: [{ name: 'stripe', hint: 'billing; webhook handler in api/webhooks/stripe' }, …],
//                                              // optional — defaults to DEFAULT_DEPENDENCIES below
//   failureModes: [{ name: 'provider-down', probe: 'what to trace…' }, …],
//                                              // optional — defaults to DEFAULT_FAILURE_MODES below
//   only: ['stripe', 'auth-provider'],         // optional subset of dependency names
//   timestamp: '2026-01-01T10:30:00-05:00',    // dispatcher-generated (no Date in scripts)
// }
//
// Derived from ProjectMuse's integration-health.js, which hardcodes 13 named integrations and
// 8 failure modes for one codebase. Both lists are args here, so the recipe travels.
let A = args || {}
if (typeof A === 'string') {
  try {
    A = JSON.parse(A)
  } catch (e) {
    return { error: 'dependency-probe: args arrived as an unparseable string — pass a JSON object' }
  }
}
if (A === null || typeof A !== 'object' || Array.isArray(A)) {
  return { error: 'dependency-probe: args must be a JSON object' }
}
if (!A.target || typeof A.target !== 'string') {
  return { error: 'dependency-probe: args.target is required — the codebase or subsystem whose dependencies are being probed' }
}
if (A.dependencies !== undefined && (!Array.isArray(A.dependencies) || !A.dependencies.length)) {
  return { error: 'dependency-probe: args.dependencies must be a non-empty array of {name, hint} when present' }
}
if (A.failureModes !== undefined && (!Array.isArray(A.failureModes) || !A.failureModes.length)) {
  return { error: 'dependency-probe: args.failureModes must be a non-empty array of {name, probe} when present' }
}

// The eight ways a third party actually fails once real traffic hits it. Every one of these is
// a production incident class, not a theoretical one: each describes a provider behaving badly
// while your code keeps running and reporting success.
const DEFAULT_FAILURE_MODES = [
  {
    name: 'provider-down',
    probe:
      'The provider is unreachable or returns 5xx. Does the affected route render a clear "could not reach X" state, or does it 500 the whole page / hang forever? Is there an explicit timeout on the outbound call, or does it inherit an unbounded default?',
  },
  {
    name: 'rate-limited',
    probe:
      'The provider returns 429 or a quota error. Is that distinguished from a real failure, is there backoff, and does a rate-limited sync mark itself for retry — or does it silently record a gap in the data as though the period had no activity? A silent gap is critical: it produces a confidently wrong result.',
  },
  {
    name: 'malformed-200',
    probe:
      'The provider returns HTTP 200 with a body that is not what the code expects — HTML error page, empty object, null where an object was promised. Is the body validated before its fields are read, or cast and trusted? Trace what reaches the database when an assumed field is missing.',
  },
  {
    name: 'timeout-mid-write',
    probe:
      'The call times out or the process dies after a multi-step or multi-page operation has partly completed. Is the partial state committed with a resumable cursor, rolled back, or half-written with no record of where it stopped?',
  },
  {
    name: 'schema-drift',
    probe:
      'The provider silently changes a field type, renames a field, or adds an enum value. Does anything detect the drift, or does it propagate as undefined/NaN/a default into stored data? Is there a pinned API version, and is an unknown enum value handled or coerced?',
  },
  {
    name: 'credential-expiry',
    probe:
      'A token, key or certificate expires, or the user revokes access at the provider. Does the refresh path handle expiry mid-request, an expired refresh token, and two concurrent refreshes racing each other? Can a user disconnect and reconnect without support, or does it retry forever in a stuck state? Confirm no secret reaches logs or the client.',
  },
  {
    name: 'duplicate-delivery',
    probe:
      'The same webhook or job is delivered twice — providers guarantee at-least-once, and workers retry. Does the handler upsert on a natural key or an idempotency key, or does it double-count, double-charge, or double-send?',
  },
  {
    name: 'out-of-order-delivery',
    probe:
      'Events arrive out of order — an update before its create, a cancellation before its subscription. Is there a sequence number, version or event timestamp guarding the write, or does the last message to arrive win and clobber newer state?',
  },
]

// Generic dependency classes. A caller with a real inventory passes args.dependencies instead;
// these defaults exist so the recipe is useful on a codebase nobody has catalogued yet.
const DEFAULT_DEPENDENCIES = [
  { name: 'http-apis', hint: 'Any third-party REST/GraphQL API the product calls directly. Find the client(s) and every call site.' },
  { name: 'auth-provider', hint: 'The identity provider: login, session refresh, JWT/JWKS verification, logout and revocation.' },
  { name: 'payments', hint: 'The payment processor: checkout, subscription state, refunds, and the billing webhook handler.' },
  { name: 'inbound-webhooks', hint: 'Every inbound webhook receiver: signature verification, replay window, idempotency, and ordering.' },
  { name: 'queues-and-workers', hint: 'Background jobs, message queues and cron: retry policy, visibility timeouts, poison messages, and idempotency of each handler.' },
  { name: 'oauth-integrations', hint: 'User-connected SaaS integrations that sync data: token storage and refresh, per-tenant scoping, pagination and cursors.' },
  { name: 'transactional-messaging', hint: 'Email, SMS and push providers: bounce and quota handling, and whether a failed send silently drops a notification the user was promised.' },
  { name: 'object-storage', hint: 'Blob/object storage and CDN: upload failure paths, signed-URL expiry, and orphaned or missing objects.' },
]

const MODES = A.failureModes || DEFAULT_FAILURE_MODES
const CATALOG = A.dependencies || DEFAULT_DEPENDENCIES
const only = Array.isArray(A.only) && A.only.length ? A.only : null
const DEPS = only ? CATALOG.filter((d) => d && only.includes(d.name)) : CATALOG
if (!DEPS.length) {
  return { error: `dependency-probe: args.only matched no dependency; valid names: ${CATALOG.map((d) => d && d.name).join(', ')}` }
}

const CHECKLIST = MODES.map((m, i) => `${i + 1}. **${m.name}** — ${m.probe}`).join('\n\n')
const MODE_NAMES = MODES.map((m) => m.name)

const PROBE_SCHEMA = {
  type: 'object',
  properties: {
    dependency: { type: 'string' },
    present: { type: 'boolean', description: 'false if this dependency does not exist in the target at all — a valid answer, not a failure' },
    modes: {
      type: 'array',
      description: 'one entry per failure mode you actually checked, mode name copied VERBATIM from the checklist',
      items: {
        type: 'object',
        properties: {
          mode: { type: 'string', description: 'the failure-mode name, copied verbatim' },
          status: { type: 'string', enum: ['handled', 'exposed', 'not-applicable'] },
          severity: {
            type: 'string',
            enum: ['critical', 'major', 'minor'],
            description: 'critical = silent data loss, a stuck state the user cannot self-recover, or a leaked credential',
          },
          evidence: { type: 'string', description: 'file:line and what the code actually does — one line, ≤300 chars' },
          fix: { type: 'string', description: 'one line, ≤300 chars' },
        },
        required: ['mode', 'status', 'evidence'],
      },
    },
  },
  required: ['dependency', 'present', 'modes'],
}

const SYNTH_SCHEMA = {
  type: 'object',
  properties: {
    sharedFate: {
      type: 'array',
      description: 'each entry is one change or condition that takes down several dependencies together',
      items: {
        type: 'object',
        properties: {
          change: { type: 'string', description: 'the single change or condition — one line, ≤300 chars' },
          breaks: { type: 'array', items: { type: 'string', description: 'dependency name it takes down' } },
          evidence: { type: 'string', description: 'the shared file(s) that create the coupling — one line, ≤300 chars' },
        },
        required: ['change', 'breaks', 'evidence'],
      },
    },
    highestLeverageFix: { type: 'string', description: 'the one change that removes the largest number of exposures — one line, ≤300 chars' },
  },
  required: ['sharedFate', 'highestLeverageFix'],
}

const STATUSES = ['handled', 'exposed', 'not-applicable']

// Every configured failure mode is reconciled BY NAME against what the prober reported, exactly
// as release-gate reconciles its requiredEvidence. A mode the prober never mentioned becomes
// 'unchecked' — never 'handled'. The difference is the whole point: "we looked and this is
// covered" and "nobody looked" are different facts, and only the first one is good news. An
// unrecognized status string also lands on 'unchecked', so a garbled report fails closed.
const reconcile = (dep, r) => {
  const reported = r && Array.isArray(r.modes) ? r.modes.filter((x) => x && typeof x.mode === 'string') : []
  const modes = MODE_NAMES.map((name) => {
    const hit = reported.find((x) => x.mode === name)
    if (hit && STATUSES.includes(hit.status)) {
      return {
        mode: name,
        status: hit.status,
        severity: hit.status === 'exposed' ? hit.severity || 'major' : '',
        evidence: hit.evidence || 'prober gave no evidence',
        fix: hit.fix || '',
      }
    }
    return {
      mode: name,
      status: 'unchecked',
      severity: 'unknown',
      evidence: r
        ? 'the prober never reported on this failure mode — it was NOT checked, and nothing is known about it'
        : 'the prober agent returned no report — nothing about this dependency is known',
      fix: '',
    }
  })
  return { dependency: dep.name, ran: !!r, present: r ? r.present !== false : null, modes }
}

phase('Probe')
log(`dependency-probe: probing ${DEPS.length} dependenc(ies) against ${MODES.length} failure mode(s) in ${A.target}`)

// WHY parallel() HERE, when pipeline() is this library's default fan-out: pipeline earns its
// place when each item has downstream per-item work that can start as soon as that item lands
// (audit verifies each finding as it arrives). This recipe has no per-item second stage. The
// only thing after Probe is Synthesize, and Synthesize is a genuine barrier — its question
// ("which single change would break the most of these at once?") is unanswerable over a subset,
// so it cannot start until every probe has resolved. With the barrier there anyway, staging the
// probes buys nothing and costs wall-clock, so they all go out at once. parallel() preserves
// array position, so index-aligned recovery below still works exactly as it does under pipeline.
const probes = await parallel(
  DEPS.map((d) => () =>
    agent(
      `You are probing ONE third-party dependency of ${A.target} for the ways it fails in PRODUCTION — not the happy path. Third-party edges are the least-tested code in most systems, because they only misbehave against the real provider.\n\n` +
        `## Dependency: ${d.name}\n${d.hint || 'Locate this dependency in the codebase yourself: find the client, the config, and every call site.'}\n\n` +
        `Trace the REAL code. For each failure mode below, report what the code does TODAY, with file:line evidence:\n\n${CHECKLIST}\n\n` +
        `Report on every failure mode you checked, individually, copying each mode name VERBATIM into the "mode" field:\n` +
        `- status="exposed": you traced a concrete path where this condition causes data loss, a stuck state the user cannot self-recover, a wrong-but-plausible result, or an unhandled crash. Give severity and a one-line fix.\n` +
        `- status="handled": you found and read the code that handles it. Cite it. Never mark handled merely because you did not find a problem.\n` +
        `- status="not-applicable": this mode cannot occur for this dependency (no webhooks at all, no credentials at all). Say why.\n\n` +
        `If you could not check a mode, LEAVE IT OUT rather than guessing. An omitted mode is recorded as UNCHECKED, which is the honest answer; a guessed "handled" is a lie this recipe cannot detect.\n\n` +
        `If this dependency does not exist in ${A.target} at all, set present=false with an empty modes array — that is a valid answer, not a failure.\n\n` +
        `READ-ONLY: read files and run read-only commands. Change NOTHING, fix NOTHING, install NOTHING, call no third-party API that writes or sends anything, and commit NOTHING — this recipe reports, a human fixes.`,
      { label: `probe:${String(d.name).slice(0, 40)}`, phase: 'Probe', schema: PROBE_SCHEMA, effort: 'high' }
    ).then((r) => reconcile(d, r))
  )
)
// A thunk that threw resolves to null. Dropping those — .filter(Boolean) — is precisely how a
// dependency disappears from a report that then reads as green and simply shorter than it should
// be, with nothing anywhere saying so. Every index is mapped back to its dependency instead.
const settled = probes.map((r, i) => r || reconcile(DEPS[i], null))

const unprobed = settled.filter((r) => !r.ran)
const rank = { critical: 0, major: 1, minor: 2 }
const exposures = settled
  .map((r) => r.modes.filter((m) => m.status === 'exposed').map((m) => ({ dependency: r.dependency, ...m })))
  .flat()
exposures.sort((a, b) => (rank[a.severity] === undefined ? 3 : rank[a.severity]) - (rank[b.severity] === undefined ? 3 : rank[b.severity]))
const unchecked = settled
  .map((r) => r.modes.filter((m) => m.status === 'unchecked').map((m) => ({ dependency: r.dependency, mode: m.mode, reason: m.evidence })))
  .flat()
log(`dependency-probe: ${exposures.length} exposure(s) across ${settled.length - unprobed.length}/${DEPS.length} dependenc(ies)${unchecked.length ? `, ${unchecked.length} mode(s) NEVER CHECKED` : ''}`)

// ---- Synthesize ----------------------------------------------------------
// This stage is why the recipe exists rather than being another `audit` checklist. Per-dependency
// probing cannot see shared fate by construction: one HTTP client with no timeout, one retry
// helper that is not idempotent, one credential used by six services. Each dependency looks
// individually acceptable and they all fall over together.
phase('Synthesize')
const digest = settled.map((r) => ({
  dependency: r.dependency,
  ran: r.ran,
  present: r.present,
  exposed: r.modes.filter((m) => m.status === 'exposed').map((m) => `${m.mode} (${m.severity}): ${m.evidence}`),
  handled: r.modes.filter((m) => m.status === 'handled').map((m) => `${m.mode}: ${m.evidence}`),
  unchecked: r.modes.filter((m) => m.status === 'unchecked').map((m) => m.mode),
}))
const synthesis = await agent(
  `You are looking for SHARED FATE across ${A.target}'s third-party dependencies — coupling that no per-dependency audit can see by construction, because it exists BETWEEN them rather than inside any one of them.\n\n` +
    `Every dependency has now been probed individually. The complete result set:\n\n${JSON.stringify(digest, null, 2)}\n\n` +
    (unprobed.length
      ? `NEVER PROBED — nothing at all is known about these, and their absence from the findings above is NOT evidence of health: ${unprobed.map((u) => u.dependency).join(', ')}\n\n`
      : '') +
    `Now read what these dependencies SHARE: the HTTP client(s), retry and backoff helpers, timeout configuration and defaults, credential storage and refresh, webhook receivers and signature verification, the queue/worker wrapper, the error boundary they all render inside. Answer one question with file evidence:\n\n` +
    `**Which single change would break the most of these at once?**\n\n` +
    `Report each shared-fate coupling as: the change or condition, the list of dependency names it takes down together, and the files that create the coupling. The shape to look for (find the real ones in this codebase — do not repeat these): one shared HTTP client with no timeout; one retry helper that is not idempotent, so every retry double-writes; one credential or signing key used by six services; one webhook receiver whose verification all providers route through; one queue whose backlog stalls every sync at once; one hand-rolled pattern copied per provider that has since drifted between copies.\n\n` +
    `Then name the single highest-leverage fix — the one change that removes the largest number of the exposures listed above.\n\n` +
    `Invent nothing. If these dependencies genuinely share no infrastructure, an empty sharedFate list is a valid and important answer — it means the blast radius is bounded, which is worth knowing.\n\n` +
    `READ-ONLY: read files and run read-only commands. Change NOTHING and commit NOTHING.`,
  { label: 'synthesize', phase: 'Synthesize', schema: SYNTH_SCHEMA, effort: 'high' }
)

// Shared recipe contract: every recipe returns `verdict`, and INCOMPLETE is reserved across all
// of them for "an agent died, so this is not a complete judgement". Three distinct events lose
// coverage here and all three outrank a clean answer:
//   - a prober died          → a dependency nobody read must never read as a dependency with no exposures
//   - a mode went unchecked  → same failure one level down, per mode
//   - the synthesizer died   → shared fate is the ONLY thing this recipe sees that a per-dependency
//     audit cannot. Losing it and still returning RESILIENT would claim the exact judgement the
//     recipe exists to make, on the strength of the one stage that did not run.
// The verdict is computed here, in code, so no agent's output can soften it.
const verdict = unprobed.length || unchecked.length || !synthesis ? 'INCOMPLETE' : exposures.length ? 'FRAGILE' : 'RESILIENT'
log(
  `dependency-probe: ${verdict} — ${exposures.length} exposure(s)${unprobed.length ? `, ${unprobed.length} dependenc(ies) NEVER PROBED` : ''}${
    unchecked.length ? `, ${unchecked.length} mode(s) NEVER CHECKED` : ''
  }${synthesis ? '' : ', SHARED-FATE SYNTHESIS NEVER RAN'}`
)

return {
  timestamp: A.timestamp || '',
  verdict,
  target: A.target,
  dependencies: DEPS.map((d) => d.name),
  failureModes: MODE_NAMES,
  results: settled,
  exposures,
  // Degraded coverage travels in the returned object, not only in log() — the caller acts on
  // what is returned, and a count that only reached the run log still leaves the report looking whole.
  unprobed,
  unchecked,
  // null (not []) when the synthesizer died: an empty list means "looked, found no shared fate",
  // which is a real and reassuring finding. Collapsing the two would hand the caller the good news
  // the stage never produced.
  sharedFate: synthesis && Array.isArray(synthesis.sharedFate) ? synthesis.sharedFate : null,
  highestLeverageFix: (synthesis && synthesis.highestLeverageFix) || '',
  synthesisRan: !!synthesis,
  synthesisNote: synthesis ? '' : 'the shared-fate synthesis agent returned no report — the cross-cutting stage NEVER RAN, so this run is INCOMPLETE, not clean',
}
