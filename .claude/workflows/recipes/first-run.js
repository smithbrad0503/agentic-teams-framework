export const meta = {
  name: 'first-run',
  description:
    "Probe a product's first-use journey — signup through first real value — for the defects that only appear with zero data and no prior state. Read-only: it reports, it never fixes.",
  whenToUse:
    'Before onboarding any beta user or customer, after shipping a feature that assumes existing data, and whenever a surface could render for an account with nothing in it. These defects are invisible to normal testing because every developer machine and every seeded environment already has data. Required inputs: product, blankSlate. Optional: entryPoints, firstValue, focus. The journey stages are discovered from the code, never passed in.',
  phases: [
    { title: 'Map', detail: 'one agent traces the real entry → first-value journey from the code' },
    { title: 'Probe', detail: 'one read-only prober per journey stage, every one assuming zero data' },
    { title: 'Verify', detail: 'adversarial refutation of each non-polish finding' },
    { title: 'Rank', detail: 'journey position as a multiplier on severity — step 1 blocks everyone' },
  ],
}

// ---- args contract -------------------------------------------------------
// {
//   product: 'Acme Billing — a Next.js 15 + Postgres monorepo, cwd = repo root',  // required
//   blankSlate: ['zero invoices', 'zero customers', 'no payment provider connected']
//               | 'one user, nothing else',                                       // required
//   entryPoints: ['app/(auth)/', 'middleware.ts', 'components/onboarding/'],       // optional reading hints
//   firstValue: 'their first invoice is sent and paid',                            // optional
//   focus: 'app/billing',                                                          // optional path prefix
//   timestamp: '2026-01-01T10:30:00-05:00',   // dispatcher-generated (no Date in scripts)
// }
// NOTE ON WHAT IS *NOT* AN ARG: the journey stages. They are discovered by the Map
// agent from the code, never declared by the caller. A caller who lists the steps
// they think exist gets the product they think they shipped probed, not the one
// they did — and the stage nobody remembered is exactly where a new user stalls.
let A = args || {}
if (typeof A === 'string') {
  try {
    A = JSON.parse(A)
  } catch (e) {
    return { error: 'first-run: args arrived as an unparseable string — pass a JSON object' }
  }
}
if (A === null || typeof A !== 'object' || Array.isArray(A)) {
  return { error: 'first-run: args must be a JSON object' }
}
if (!A.product || typeof A.product !== 'string') {
  return { error: 'first-run: args.product is required — one line naming the product and its stack, so agents know what they are reading' }
}
const BLANK = Array.isArray(A.blankSlate) ? A.blankSlate.filter((b) => typeof b === 'string' && b.trim()).join(', ') : String(A.blankSlate || '').trim()
if (!BLANK) {
  return { error: 'first-run: args.blankSlate is required — spell out what "zero data, no prior state" means for THIS product; it is the precondition the whole recipe applies' }
}

const PRODUCT = A.product
const FIRST_VALUE = A.firstValue || 'the first moment the user gets real value out of the product, not merely a completed signup form'
const FOCUS = A.focus || null
const ENTRY_HINTS = Array.isArray(A.entryPoints) ? A.entryPoints.filter((e) => typeof e === 'string' && e.trim()) : []

const JOURNEY_SCHEMA = {
  type: 'object',
  properties: {
    stages: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          name: { type: 'string', description: 'short stage name, in journey order' },
          entryPoint: { type: 'string', description: 'route, file or command where this stage begins' },
          surfaces: { type: 'array', items: { type: 'string' }, description: 'routes/components/screens a brand-new user sees at this stage' },
          dataAssumed: { type: 'string', description: 'what data or prior state this stage silently assumes already exists' },
        },
        required: ['name', 'entryPoint'],
      },
    },
    seedDependencies: {
      type: 'array',
      items: { type: 'string' },
      description: 'anything that only works because dev/seed/demo data exists — hardcoded ids, fixtures referenced outside tests, ranges anchored to seed data',
    },
  },
  required: ['stages'],
}

const PROBE_SCHEMA = {
  type: 'object',
  properties: {
    stage: { type: 'string' },
    issues: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          title: { type: 'string', description: 'one line naming the defect' },
          surface: { type: 'string', description: 'route + file:line' },
          whatUserSees: { type: 'string', description: 'concretely what renders for a zero-data account: blank area, spinner forever, error toast, crash, a misleading zero, a required field they cannot fill' },
          severity: { type: 'string', enum: ['blocker', 'major', 'polish'], description: 'blocker = the new user cannot proceed, or believes the product is broken' },
          fix: { type: 'string', description: 'the smallest real fix' },
        },
        required: ['title', 'surface', 'whatUserSees', 'severity'],
      },
    },
    workedFine: { type: 'array', items: { type: 'string' }, description: 'surfaces that correctly handle zero data — evidence the stage was actually read' },
  },
  required: ['stage', 'issues'],
}

const VERDICT_SCHEMA = {
  type: 'object',
  properties: {
    refuted: { type: 'boolean', description: 'true if the claimed defect does not really happen for a brand-new account' },
    reasoning: { type: 'string', description: 'one line, ≤300 chars — cite what you read that decided it' },
  },
  required: ['refuted', 'reasoning'],
}

// THE UNIFORM COUNTERFACTUAL. This exact framing is prepended to every prompt in
// every stage — Map, Probe and Verify — because the defects this recipe exists to
// find are defects of ABSENCE, and absence is only visible to an agent that has been
// told to assume it. A prober that reasons about "a typical user" reasons about a
// populated account and finds nothing, because with data everything works.
const PREAMBLE = `You are tracing the very first run of ${PRODUCT} — a real person who just signed up, moments in.

THE PRECONDITION, applied to every question you ask at every stage: assume ZERO DATA and NO PRIOR STATE. Nothing has been seeded, imported, connected, invited, purchased or configured. Concretely, for this product that means: ${BLANK}.

This is a CODE-TRACING exercise. Read the routes, components and data paths and reason about what actually renders when every query returns an empty result, every integration is unauthorized, and every "recent" / "top" / "summary" surface has nothing to summarize.

WHY THIS MATTERS: every developer machine and every seeded environment already has data, so these paths are the least-exercised code in the product and the first thing a real new user hits. The failures are failures of absence — the empty state nobody built, the tour that assumes a populated dashboard, the required field with no way to obtain a valid value yet, the step that silently requires an invite.

First value, for this product, means: ${FIRST_VALUE}.

READ-ONLY: read files, grep, and list directories. Change NOTHING, fix NOTHING, run no migrations, commit NOTHING — this recipe reports, a human fixes. Report only what you traced in real code; an empty findings list is a valid, good result and is better than an invented one.${FOCUS ? `\n\nFocus area: ${FOCUS} — stay inside it.` : ''}`

const mapPrompt = `${PREAMBLE}

Task: MAP the first-run journey. Discover it from the code — do not assume a conventional signup flow, and do not stop at the routes that are easy to find.

${ENTRY_HINTS.length ? `Start reading here, then follow the code outward: ${ENTRY_HINTS.join(', ')}.` : 'Find the entry point yourself: look for auth/signup routes, middleware or route guards, onboarding or setup components, first-launch checks, and the invite/registration handlers.'}

Produce the ORDERED stages a brand-new user passes through, from the entry point through to first value as defined above. For each stage give: its entry point, the surfaces (routes/components/screens) the new user sees there, and — most importantly — what data or prior state that stage silently assumes already exists.

Also list seedDependencies: anything in the codebase that only works because dev/seed/demo data exists (hardcoded ids, fixtures referenced outside tests, ranges anchored to seeded rows, defaults that are only created by a seed script).`

const probePrompt = (s) => `${PREAMBLE}

Task: probe ONE stage of the first-run journey for zero-data failures.

## Stage: ${s.name}
Entry point: ${s.entryPoint}
Surfaces: ${(s.surfaces || []).join(', ') || '(discover them yourself)'}
Data this stage assumes: ${s.dataAssumed || '(determine it yourself)'}

For every surface in this stage, trace what renders when the underlying queries return empty:
- Is there an explicit empty state, and does it tell the user what to DO next (not just "No data")?
- Lists, tables, charts and visualizations with an empty series — blank box, broken axis, or a crash?
- Aggregates over empty sets — does a sum/average/percentage produce NaN, Infinity, or a "0" presented as if it were a real measurement?
- Loading states that never resolve because the fetch short-circuits, errors, or is never triggered on an empty result.
- Anything gated on an integration, import or invite the user has not completed — does it explain how to proceed, or just fail silently?
- Required inputs with no valid value obtainable yet: a required selector whose options come from data that cannot exist yet, a form that cannot be submitted until something else exists.
- Generated or summarized surfaces (digests, briefs, recommendations, AI output) with nothing to summarize — what does the prompt produce, and is an empty or invented result shown to the user as fact?
- Permission-gated or role-gated areas rendering as blank pages rather than an explanation.
- Any \`.length\`, \`[0]\`, \`.map\`, destructuring or index access on a possibly-empty result without a guard, and any division by a possibly-zero count.

Report what you traced, with the concrete user-visible outcome for each issue. List in workedFine the surfaces you checked that handle zero data correctly — that list is the evidence you read the stage rather than guessed it.`

// The verifier gets the same precondition as the prober. Handed only the claim, it
// re-reads the code as a normal user with normal data and "refutes" a real defect.
const verifyPrompt = (i, s) => `${PREAMBLE}

Task: adversarially verify ONE claimed first-run defect. Open ${i.surface} and the code around it yourself — do not take the claim on trust, and do not take it on suspicion either.

Stage: ${s.name} (${s.entryPoint})
Claim (${i.severity}): ${i.title}
Asserted user experience: ${i.whatUserSees}

REFUTE it if any of these is true, and say which:
- an empty state IS implemented — check parent components, layout wrappers, loading/error boundaries, and any shared table/list/chart component that renders its own empty state;
- the surface is unreachable for a brand-new account — feature-flagged off, role-gated away, or behind a step that must complete first;
- the data is actually guaranteed non-empty at signup — defaults created by a trigger, migration, or template provisioned on account creation. Read the account-creation path before concluding a table is empty.

refuted=true when the defect does not really happen, and when you are genuinely uncertain. Confirm only what you can point at in code.

READ-ONLY: read and grep, change NOTHING.`

// ---------- Map ----------
phase('Map')
const journey = await agent(mapPrompt, { label: 'map:journey', phase: 'Map', schema: JOURNEY_SCHEMA, effort: 'high' })
if (!journey || !Array.isArray(journey.stages) || !journey.stages.length) {
  // A dead mapper is not a product with no journey. Falling through with zero stages
  // would probe nothing and return an empty findings list — a clean bill of health for
  // a product nobody read. INCOMPLETE, and the error says which stage died.
  log('first-run: map agent returned no journey — nothing was probed')
  return {
    timestamp: A.timestamp || '',
    verdict: 'INCOMPLETE',
    error: 'first-run: map agent returned no journey — the first-run path was never traced, so nothing was probed',
    product: PRODUCT,
    journey: [],
    seedDependencies: [],
    coverage: { stagesRequested: 0, stagesProbed: 0 },
    findings: [],
    unverified: [],
    unprobed: [],
    handledWell: [],
    refutedCount: 0,
  }
}
const stages = journey.stages.filter((s) => s && s.name && s.entryPoint)
if (!stages.length) {
  log('first-run: map agent returned stages with no usable name/entryPoint — nothing was probed')
  return {
    timestamp: A.timestamp || '',
    verdict: 'INCOMPLETE',
    error: 'first-run: mapped stages carried no usable name/entryPoint — nothing was probed',
    product: PRODUCT,
    journey: [],
    seedDependencies: journey.seedDependencies || [],
    coverage: { stagesRequested: journey.stages.length, stagesProbed: 0 },
    findings: [],
    unverified: [],
    unprobed: [],
    handledWell: [],
    refutedCount: 0,
  }
}
log(`first-run: mapped ${stages.length} journey stage(s) — ${stages.map((s) => s.name).join(' → ')}`)

// ---------- Probe each stage, verifying its findings as it completes ----------
phase('Probe')
const probes = await pipeline(
  stages,
  (s) => agent(probePrompt(s), { label: `probe:${String(s.name).slice(0, 24)}`, phase: 'Probe', schema: PROBE_SCHEMA, effort: 'high' }),
  (r, s) => {
    // A prober that returned nothing is NOT a stage with no problems. Returning an
    // empty findings list here is how a whole stage of the journey disappears into a
    // result that reads as "checked, clean".
    if (!r || !Array.isArray(r.issues)) {
      return { stage: s.name, unprobed: true, reason: 'probe agent returned no report', findings: [], workedFine: [] }
    }
    const issues = r.issues.filter((i) => i && i.title && i.severity)
    const serious = issues.filter((i) => i.severity !== 'polish')
    // `unchallenged` is deliberately NOT `unverified`: polish findings are skipped by
    // policy because verifying them costs more than reading them, whereas `unverified`
    // means an agent died. Only the second one is allowed to make a run INCOMPLETE.
    const polish = issues
      .filter((i) => i.severity === 'polish')
      .map((i) => ({ ...i, stage: s.name, verdict: 'unchallenged', verifyReason: 'polish findings are reported unchallenged by policy — not sent to a verifier' }))
    if (!serious.length) return { stage: s.name, findings: polish, workedFine: r.workedFine || [] }
    return parallel(
      serious.map((i) => () =>
        agent(verifyPrompt(i, s), { label: `verify:${String(i.surface || s.name).split('/').pop().slice(0, 32)}`, phase: 'Verify', schema: VERDICT_SCHEMA, effort: 'high' }).then((v) => ({
          // A verifier that DIED is not a verifier that refuted. Collapsed into one
          // falsy state, a crashed verifier silently exonerates the defect and it drops
          // out of the report — the run fails OPEN and looks better than the product is.
          // Three states, always: confirmed | refuted | unverified.
          ...i,
          stage: s.name,
          verdict: v ? (v.refuted ? 'refuted' : 'confirmed') : 'unverified',
          verifyReason: (v && v.reasoning) || 'verifier agent returned no report',
        }))
      )
    ).then((verified) => ({
      stage: s.name,
      // `parallel` yields null where a thunk threw, aligned with its input. `.filter(Boolean)`
      // here is precisely how a finding vanishes, so every index is mapped back to the
      // issue it came from and marked unverified instead.
      findings: verified
        .map((v, idx) => v || { ...serious[idx], stage: s.name, verdict: 'unverified', verifyReason: 'verifier agent errored before returning' })
        .concat(polish),
      workedFine: r.workedFine || [],
    }))
  }
)

// `pipeline` preserves stage order and yields null where a stage thunk threw. Recovered
// by index against `stages`, never filtered — a stage that errored must appear as a hole
// in coverage, not as a stage with nothing wrong.
const settled = probes.map((p, i) => p || { stage: stages[i].name, unprobed: true, reason: 'probe stage errored before returning', findings: [], workedFine: [] })
const unprobed = settled.filter((p) => p.unprobed).map((p) => ({ stage: p.stage, reason: p.reason }))
const all = settled.map((p) => p.findings || []).flat()
const confirmed = all.filter((f) => f.verdict === 'confirmed')
const unchallenged = all.filter((f) => f.verdict === 'unchallenged')
const unverified = all.filter((f) => f.verdict === 'unverified')
const refutedCount = all.filter((f) => f.verdict === 'refuted').length

// ---------- Rank ----------
phase('Rank')
// Journey position is a MULTIPLIER on severity, not a tie-break after it. A blocker at
// step 1 is hit by 100% of new users; the same blocker at step 9 is hit only by the few
// who got that far — and they got that far, so the product already worked for them.
// Ranking by severity alone puts a late blocker above an early major and sends the team
// to fix the defect fewer people ever reach.
const stageOrder = {}
stages.forEach((s, idx) => {
  stageOrder[s.name] = idx
})
const TOTAL = stages.length
const SEV_WEIGHT = { blocker: 100, major: 20, polish: 3 }
const positionOf = (stage) => (stageOrder[stage] === undefined ? TOTAL - 1 : stageOrder[stage])
const ranked = confirmed
  .concat(unchallenged)
  .map((f) => {
    const position = positionOf(f.stage)
    return { ...f, position, score: Math.round((SEV_WEIGHT[f.severity] || 1) * ((TOTAL - position) / TOTAL) * 100) / 100 }
  })
  // Ties break on position then title so the ordering is fully determined by the data:
  // a resumed run replays this sort and must produce the same report.
  .sort((a, b) => b.score - a.score || a.position - b.position || (a.title < b.title ? -1 : a.title > b.title ? 1 : 0))

const blockers = ranked.filter((f) => f.severity === 'blocker' && f.verdict === 'confirmed')
// Shared recipe contract: every recipe returns `verdict`, and INCOMPLETE is reserved
// across all of them for "an agent died, so this is not a complete judgement". A stage
// never probed and a defect never verified both cost coverage, and a run that lost
// coverage is not entitled to READY — or even to BLOCKED, which invites "fix that one
// and ship". INCOMPLETE outranks both.
const verdict = unprobed.length || unverified.length ? 'INCOMPLETE' : blockers.length ? 'BLOCKED' : ranked.length ? 'ROUGH' : 'READY'
log(
  `first-run: ${verdict} — ${ranked.length} finding(s), ${blockers.length} blocker(s) across ${settled.length - unprobed.length}/${stages.length} stage(s)` +
    `${unprobed.length ? `, ${unprobed.length} STAGE(S) NEVER PROBED` : ''}${unverified.length ? `, ${unverified.length} UNVERIFIED (verifier failed — treat as real until checked by hand)` : ''}`
)

return {
  timestamp: A.timestamp || '',
  verdict,
  product: PRODUCT,
  firstValue: FIRST_VALUE,
  journey: stages.map((s) => s.name),
  seedDependencies: journey.seedDependencies || [],
  coverage: { stagesRequested: stages.length, stagesProbed: settled.length - unprobed.length },
  findings: ranked.map((f) => ({
    score: f.score,
    severity: f.severity,
    stage: f.stage,
    position: f.position + 1,
    surface: f.surface,
    title: f.title,
    whatUserSees: f.whatUserSees,
    fix: f.fix,
    verdict: f.verdict,
  })),
  // Degraded items are RETURNED, not merely counted in the log: the caller acts on this
  // object, and an unverified defect is the one most likely to be real and unattended.
  unverified,
  unprobed,
  refutedCount,
  handledWell: settled.map((p) => (p.workedFine || []).map((w) => ({ stage: p.stage, surface: w }))).flat(),
}
