export const meta = {
  name: 'state-reconcile',
  description: 'Reconcile what a tracking system CLAIMS against what reality SHOWS, using two blind independent gatherers, and report the drift between them. Report-only by default; writes back ONLY the specific fields the caller names in writeBack.fields.',
  phases: [
    { title: 'Gather', detail: 'two blind agents in parallel: one records the claim, one observes reality — neither sees the other' },
    { title: 'Reconcile', detail: 'diff the two pictures into an evidence-backed drift list' },
    { title: 'Write', detail: 'opt-in only: ONE writer edits only the authorized fields' },
  ],
}

// ---- args contract -------------------------------------------------------
// {
//   subject: 'sprint board vs. what git shows shipped',   // required, one line — what is being reconciled
//   claim: {                                              // required — the tracking system
//     label: 'task-board.json + sprint.md',
//     instructions: 'read .claude/orchestrator/sprint.md and task-board.json; report every ticket …',
//   },
//   reality: {                                            // required — the observable world
//     label: 'git history on main',
//     instructions: 'git log --no-merges since the sprint start; group commits into shipped units …',
//   },
//   asOf: '2026-07-25T00:00:00-04:00',   // optional — the moment staleness is judged against; defaults to timestamp
//   timestamp: '2026-07-25T10:30:00-04:00',  // REQUIRED, dispatcher-generated (no Date in scripts)
//   writeBack: {                          // OPTIONAL and OPT-IN. Absent ⇒ report only, nothing is written.
//     fields: ['task-board.json:status'], // required when writeBack is present; the ONLY fields that may change
//     instructions: 'edit surgically; sprint.md is parsed by the session-start hook, keep its headings',
//     branch: 'chore/state-reconcile',    // optional; empty ⇒ writer stays on the current branch
//   },
// }
//
// Shape: a claim, a reality, and the difference. It fits a task board vs. git history,
// a roadmap vs. shipped features, a dependency manifest vs. what is actually imported,
// documented endpoints vs. routed ones, a status page vs. measured health.
//
// This also generalizes the "Librarian" on docs/ROADMAP.md (v0.6.0 — flag context packs
// whose staleness date predates recent merges in their zones): claim = each pack's recorded
// staleness date, reality = merge dates in that pack's ownership zone, drift = a pack that
// reality has moved past. The roadmap entry specifies "flag-only, never auto-rewrite" —
// which is this recipe's default, and the reason write-back had to be opt-in.
let A = args || {}
if (typeof A === 'string') {
  try {
    A = JSON.parse(A)
  } catch (e) {
    return { error: 'state-reconcile: args arrived as an unparseable string — pass a JSON object' }
  }
}
if (A === null || typeof A !== 'object' || Array.isArray(A)) {
  return { error: 'state-reconcile: args must be a JSON object' }
}
// Validate EVERYTHING before the first agent() call: a reconciliation spawned against a
// half-specified side produces a drift list that is really a spec bug, and it has already
// cost two high-effort agents by the time anyone reads it.
if (!A.subject || typeof A.subject !== 'string') {
  return { error: 'state-reconcile: args.subject must be a one-line description of what is being reconciled' }
}
if (!A.claim || !A.claim.instructions) {
  return { error: 'state-reconcile: args.claim.instructions is required — what the tracking system says, and where to read it' }
}
if (!A.reality || !A.reality.instructions) {
  return { error: 'state-reconcile: args.reality.instructions is required — what reality shows, and how to observe it' }
}
if (!A.timestamp) {
  return { error: 'state-reconcile: args.timestamp required (workflow scripts cannot call Date, and this recipe judges staleness)' }
}
// Write-back is opt-in AND bounded, in that order. `writeBack: {}` is a caller who wants
// writes but has not said which — that is precisely the wholesale overwrite this recipe
// refuses, so it is an error rather than a permissive default.
if (A.writeBack !== undefined && A.writeBack !== null) {
  if (typeof A.writeBack !== 'object' || Array.isArray(A.writeBack)) {
    return { error: 'state-reconcile: args.writeBack must be an object {fields: [...], instructions?, branch?}' }
  }
  if (!Array.isArray(A.writeBack.fields) || !A.writeBack.fields.length) {
    return { error: 'state-reconcile: args.writeBack.fields must be a non-empty array naming exactly which fields may be written — this recipe never writes anything a caller did not name' }
  }
}

const SUBJECT = String(A.subject)
// No wall clock anywhere in this file: staleness is judged against a caller-supplied
// moment. A resumed Workflow replays the script, and a wall-clock read here would make the
// replay of a *staleness* recipe disagree with the original run about what is stale. (The
// forbidden constructs cannot even be named in this file: tests/test_recipes.py greps the
// raw source, comments included, which is the correct strictness for a rule this cheap.)
const AS_OF = A.asOf || A.timestamp
const CLAIM_LABEL = (A.claim.label && String(A.claim.label)) || 'the tracking system'
const REALITY_LABEL = (A.reality.label && String(A.reality.label)) || 'observed reality'
const WB = A.writeBack || null
const ALLOWED = WB ? WB.fields.map(String) : []
const WB_BRANCH = (WB && WB.branch) || ''
const WB_NOTES = (WB && WB.instructions) || ''

const CLAIM_SCHEMA = {
  type: 'object',
  properties: {
    sources: { type: 'array', items: { type: 'string' }, description: 'the exact files/records read' },
    claims: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          item: { type: 'string', description: 'the thing being tracked — ticket id, package name, endpoint, pack name' },
          claimedState: { type: 'string', description: 'what the record says about it, verbatim' },
          claimedAt: { type: 'string', description: 'the date the record itself carries, verbatim; empty string if it carries none — never guess one' },
          source: { type: 'string', description: 'file and line/section this claim came from' },
        },
        required: ['item', 'claimedState', 'source'],
      },
    },
    unreadable: { type: 'array', items: { type: 'string' }, description: 'sources that could not be read, one line each with why — never omit one silently' },
  },
  required: ['claims'],
}
const REALITY_SCHEMA = {
  type: 'object',
  properties: {
    sources: { type: 'array', items: { type: 'string' }, description: 'the exact commands run / artifacts inspected' },
    observations: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          item: { type: 'string', description: 'the thing observed, named as reality names it' },
          observedState: { type: 'string', description: 'what is actually the case' },
          evidence: { type: 'string', description: 'sha, file path, command output, route — something a human can re-check' },
          observedAt: { type: 'string', description: 'the date reality carries (commit date, mtime), verbatim; empty string if none' },
        },
        required: ['item', 'observedState', 'evidence'],
      },
    },
    unreadable: { type: 'array', items: { type: 'string' }, description: 'anything that could not be observed, one line each with why — never omit one silently' },
  },
  required: ['observations'],
}
const DRIFT_SCHEMA = {
  type: 'object',
  properties: {
    summary: { type: 'string', description: 'one truthful line: the state of this subject as of now' },
    drift: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          item: { type: 'string' },
          field: { type: 'string', description: 'the specific writable field this drift would correct, as "<file or record>:<field>" — this is what a caller authorizes' },
          claimSays: { type: 'string' },
          realitySays: { type: 'string' },
          evidence: { type: 'string', description: 'the reality-side evidence, so a human can re-check without re-running this' },
          direction: { type: 'string', enum: ['claim-ahead', 'reality-ahead', 'conflict'], description: 'claim-ahead = the record claims more than reality supports (the dangerous one); reality-ahead = shipped/changed but unrecorded' },
          staleSince: { type: 'string', description: 'the date after which the claim stopped being true, from the dates in the inputs; empty string if undeterminable' },
          confidence: { type: 'string', enum: ['high', 'low'] },
        },
        required: ['item', 'field', 'claimSays', 'realitySays', 'evidence', 'direction'],
      },
    },
    claimedOnly: { type: 'array', items: { type: 'string' }, description: 'tracked items reality shows no trace of at all' },
    realityOnly: { type: 'array', items: { type: 'string' }, description: 'real things no record mentions at all — this is how post-sprint bursts get lost' },
  },
  required: ['summary', 'drift'],
}
const WRITE_SCHEMA = {
  type: 'object',
  properties: {
    filesChanged: { type: 'array', items: { type: 'string' } },
    applied: { type: 'array', items: { type: 'string' }, description: 'one line per change actually made: item, field, old value → new value' },
    notApplied: { type: 'array', items: { type: 'string' }, description: 'anything authorized but not written, with the reason — never omit one silently' },
    touchedOutsideAuthorization: { type: 'array', items: { type: 'string' }, description: 'anything changed that was NOT in the authorized field list; should be empty, and must be reported if not' },
  },
  required: ['filesChanged', 'applied', 'notApplied'],
}

// ===========================================================================
// THE BLIND DOUBLE-GATHER — hard structure, not a style choice. Do not "simplify"
// this into one agent, and do not thread either result into the other's prompt.
//
// Drift is only trustworthy if the two pictures were formed independently. An agent
// shown the board first will rationalize the git history until it matches — it reads
// the claim as the answer key and goes looking for confirmation, and the drift list
// it produces is a measure of its own agreeableness, not of the project. The whole
// value of this recipe is that neither gatherer could have been influenced.
//
// Three things enforce it, on purpose, at three different levels:
//   1. TEMPORAL — both thunks are handed to ONE parallel() call, so they are in flight
//      at the same time and neither result exists while the other prompt is being used.
//   2. LEXICAL — both prompts are frozen into consts BELOW this comment and ABOVE the
//      `const [claimSide, realitySide] = await parallel(...)` line. The result bindings
//      are in the temporal dead zone up there: an edit that interpolates `realitySide`
//      into CLAIM_PROMPT is a ReferenceError on the first run, not a subtle bias.
//   3. IN WORDS — each prompt names the other side's sources and forbids touching them,
//      because a curious agent will otherwise go read them unasked.
// tests/test_recipe_state_reconcile.py pins all three.
// ===========================================================================
const CLAIM_PROMPT =
  `You are the CLAIM gatherer for a reconciliation of: ${SUBJECT}\n\n` +
  `Record what the tracking system — ${CLAIM_LABEL} — CLAIMS, faithfully and verbatim, WITHOUT checking whether any of it is true.\n\n` +
  `Where to read and what to extract:\n${A.claim.instructions}\n\n` +
  `Treat ${AS_OF} as the current moment; you have no other clock. Copy each record's own date into claimedAt verbatim, or leave it empty — never infer one.\n\n` +
  `BLIND: a second agent is independently observing reality right now, and you must not see, seek, or anticipate its picture. Do NOT inspect git history, run the test suite, hit endpoints, or examine the running system — corroborate NOTHING. Report claims exactly as written even where they look obviously wrong. Contradicting the record is a later stage's job, and a gatherer that quietly pre-corrects it erases the very difference this recipe exists to measure.\n\n` +
  `List anything you could not read in \`unreadable\` — a source you skipped must never look like a source with nothing in it.\n\n` +
  `READ-ONLY: read files and run read-only commands. Change NOTHING, fix NOTHING, commit NOTHING.`

const REALITY_PROMPT =
  `You are the REALITY gatherer for a reconciliation of: ${SUBJECT}\n\n` +
  `Establish what is ACTUALLY the case — ${REALITY_LABEL} — from primary evidence only.\n\n` +
  `What to observe and how:\n${A.reality.instructions}\n\n` +
  `Treat ${AS_OF} as the current moment; you have no other clock. Copy the date reality carries (commit date, file mtime, release date) into observedAt verbatim, or leave it empty — never infer one.\n\n` +
  `BLIND: a second agent is independently reading the tracking system right now, and you must not see, seek, or anticipate its picture. Do NOT open the board, roadmap, sprint file, status page, changelog, manifest, or any other record that CLAIMS what the state is — including any narrative in README or docs. If a record is the only place a fact appears, that fact is not evidence; leave it out. Report what you can prove, even where it is embarrassing or contradicts what you would expect the plan to say.\n\n` +
  `Every observation needs evidence a human can re-check by hand. List anything you could not observe in \`unreadable\` — an unobserved thing must never look like an absent thing.\n\n` +
  `READ-ONLY: read files and run read-only commands. Change NOTHING, fix NOTHING, commit NOTHING.`

phase('Gather')
const [claimSide, realitySide] = await parallel([
  () => agent(CLAIM_PROMPT, { label: 'gather:claim', phase: 'Gather', schema: CLAIM_SCHEMA, effort: 'high' }),
  () => agent(REALITY_PROMPT, { label: 'gather:reality', phase: 'Gather', schema: REALITY_SCHEMA, effort: 'high' }),
])

// A dead gatherer is the sharpest failure mode this recipe has: an ABSENT picture and an
// AGREEING picture are the same empty diff. Filtering the falsy side out here would leave
// one side, produce zero drift, and report ALIGNED — a reconciliation that reconciled nothing,
// reading exactly like a clean bill of health. So the loss is named, and `drift` comes back
// as null rather than [] — an empty array is a claim that the diff was computed and was
// empty, which is the one thing that is definitely not true here.
const lost = []
if (!claimSide) lost.push({ side: 'claim', label: CLAIM_LABEL, reason: 'claim gatherer returned no report' })
if (!realitySide) lost.push({ side: 'reality', label: REALITY_LABEL, reason: 'reality gatherer returned no report' })
if (lost.length) {
  log(`state-reconcile: INCOMPLETE — ${lost.map((l) => l.side).join(' and ')} gatherer(s) returned nothing; drift CANNOT be computed from one side`)
  return {
    timestamp: A.timestamp,
    subject: SUBJECT,
    verdict: 'INCOMPLETE',
    summary: 'drift was not computed — a gatherer produced no picture, and one side is not a reconciliation',
    drift: null,
    driftCount: null,
    claimedOnly: [],
    realityOnly: [],
    mode: ALLOWED.length ? 'write-back' : 'report-only',
    authorizedFields: ALLOWED,
    withheld: [],
    wrote: null,
    lost,
    nextStep: 'Re-run. Do NOT read `drift: null` as "no drift" — nothing was compared.',
  }
}

const claims = claimSide.claims || []
const observations = realitySide.observations || []
const unreadable = (claimSide.unreadable || []).map((u) => `claim: ${u}`).concat((realitySide.unreadable || []).map((u) => `reality: ${u}`))
log(`state-reconcile: claim side reports ${claims.length} tracked item(s); reality side reports ${observations.length} observation(s)${unreadable.length ? `; ${unreadable.length} source(s) UNREADABLE` : ''}`)

phase('Reconcile')
// The reconciler is the first agent allowed to see both pictures — and it is deliberately
// NOT told which fields the caller authorized for write-back. A drift list tailored to what
// it is permitted to fix is a shorter drift list, and the unauthorized findings are exactly
// the ones a human needs to see. Authorization is applied in code, below, after the list is
// complete.
const rec = await agent(
  `Reconcile a tracking system against reality for: ${SUBJECT}\n\n` +
    `These two pictures were gathered INDEPENDENTLY and BLIND — neither gatherer saw the other's output. Where they disagree, that disagreement is real signal, not a coordination artifact.\n\n` +
    `## What ${CLAIM_LABEL} CLAIMS\n` +
    (claims.map((c) => `- ${c.item}: ${c.claimedState}${c.claimedAt ? ` (recorded ${c.claimedAt})` : ''} [${c.source}]`).join('\n') || '(nothing claimed)') +
    `\n\n## What ${REALITY_LABEL} SHOWS\n` +
    (observations.map((o) => `- ${o.item}: ${o.observedState} — ${o.evidence}${o.observedAt ? ` (${o.observedAt})` : ''}`).join('\n') || '(nothing observed)') +
    (unreadable.length ? `\n\n## Sources NEITHER side could read (treat as unknown, never as agreement)\n- ${unreadable.join('\n- ')}` : '') +
    `\n\nTreat ${AS_OF} as the current moment; you have no other clock. Judge staleness against it and against the dates above only.\n\n` +
    `Produce the drift list. Rules:\n` +
    `- **Reality is the source of truth for what IS.** A record claiming otherwise is drift, however confidently it is written.\n` +
    `- The two sides name things differently. Match them on substance before calling something missing, and read the underlying files where a match is uncertain.\n` +
    `- Only genuine divergences belong in \`drift\`. Agreement is a real and good result — do not manufacture drift to look thorough.\n` +
    `- \`field\` must name the ONE specific writable field a correction would touch, as "<file or record>:<field>". A caller authorizes writes by that exact string, so be precise and consistent.\n` +
    `- \`direction\`: claim-ahead when the record claims more than reality supports; reality-ahead when something real is unrecorded; conflict when both assert incompatible things.\n` +
    `- \`staleSince\`: the date the claim stopped being true, drawn from the dates above. Empty string when the inputs cannot establish one — do not estimate.\n` +
    `- \`confidence: 'low'\` for anything resting on a name match, an inference, or a source listed as unreadable. Low-confidence drift is still reported; it is not silently dropped.\n` +
    `- \`claimedOnly\` / \`realityOnly\`: items only one side knows about at all.\n\n` +
    `READ-ONLY: you may read files to check a claim, but change NOTHING, fix NOTHING, commit NOTHING. This stage decides; it does not repair.`,
  { label: 'reconcile', phase: 'Reconcile', schema: DRIFT_SCHEMA, effort: 'high' }
)

// Same rule one stage down: a dead reconciler did not find zero drift, it found nothing at
// all. `drift: null` again, and INCOMPLETE — the gathered pictures are returned raw so the
// run is not a total loss and a human can do the diff by eye.
if (!rec) {
  log('state-reconcile: INCOMPLETE — reconciler returned no report; the two pictures are returned undiffed')
  return {
    timestamp: A.timestamp,
    subject: SUBJECT,
    verdict: 'INCOMPLETE',
    summary: 'drift was not computed — the reconciler produced no report',
    drift: null,
    driftCount: null,
    claimedOnly: [],
    realityOnly: [],
    mode: ALLOWED.length ? 'write-back' : 'report-only',
    authorizedFields: ALLOWED,
    withheld: [],
    wrote: null,
    lost: [{ side: 'reconcile', label: 'reconciler', reason: 'reconcile agent returned no report' }],
    gathered: { claims, observations, unreadable },
    nextStep: 'Re-run. `drift: null` means nothing was compared — the raw pictures are under `gathered`.',
  }
}

const drift = rec.drift || []
// Partition, never filter-and-forget: `authorized` and `withheld` are both returned and
// together they are the whole drift list. Nothing leaves this recipe by being unauthorized.
const authorized = ALLOWED.length ? drift.filter((d) => ALLOWED.indexOf(String(d.field)) >= 0) : []
const withheld = drift
  .filter((d) => authorized.indexOf(d) < 0)
  .map((d) => ({ ...d, withheldReason: ALLOWED.length ? `field "${d.field}" is not in the authorized list` : 'report-only run — no writeBack.fields were given' }))
log(`state-reconcile: ${drift.length} drift item(s)${ALLOWED.length ? ` — ${authorized.length} authorized to write, ${withheld.length} reported only` : ' — report-only, nothing will be written'}`)

// ---- Write-back: opt-in, bounded, and one writer -------------------------
// The default is report-only, and that is a deliberate repetition of a decision this repo
// already made: scripts/run_metrics.py's `--reconcile` reports board-vs-PR disagreements
// and NEVER writes board.json, because `done` is a human's judgement, not a fact the runner
// produced — "silently rewriting state that a human curates is exactly the wrong default".
// Tracking state is curated the same way here, so the same rule applies: report by default,
// and when the caller does opt in, change only the exact fields they named. There is no
// wholesale-overwrite path in this recipe, and adding one would delete the signal it exists
// to surface. One writer, serialized, for the same reason batch-author.js has one: these
// items land in the same files.
let wrote = null
if (ALLOWED.length && authorized.length) {
  phase('Write')
  wrote = await agent(
    `Apply ${authorized.length} authorized correction(s) to the tracking system for: ${SUBJECT}\n\n` +
      `## The ONLY fields you may change\n- ${ALLOWED.join('\n- ')}\n\n` +
      `## The corrections\n` +
      authorized.map((d) => `- ${d.item} — ${d.field}: currently "${d.claimSays}", reality shows "${d.realitySays}" (evidence: ${d.evidence})${d.confidence === 'low' ? ' [LOW CONFIDENCE — apply only if the file confirms it; otherwise list it in notApplied]' : ''}`).join('\n') +
      `\n\n${WB_BRANCH ? `Create or switch to branch "${WB_BRANCH}" from the default branch before editing.` : 'No branch was given: edit on the CURRENT branch, and if that is the default branch, write NOTHING and say so in notApplied.'}\n\n` +
      (WB_NOTES ? `## Caller's editing notes\n${WB_NOTES}\n\n` : '') +
      `Rules — these are the boundary of your authorization, not advice:\n` +
      `- Edit ONLY the fields listed above, ONLY for the items listed above. Everything else in every file you open is out of scope, including things that look wrong, stale, or trivially fixable. A different agent's finding is not yours to fix.\n` +
      `- Surgical edits only. Never rewrite or regenerate a whole file, never reformat, never reorder, never "clean up" adjacent entries. Preserve existing structure, headings, key order and formatting exactly — other tooling parses these files.\n` +
      `- You are the ONLY agent writing these files in this run: no other writer is active now and none will run after you. Do not coordinate, do not re-read for concurrent changes.\n` +
      `- Read each file before editing and confirm the current value matches "currently" above. If it does not, the drift has moved since it was measured — do not force the edit; put it in notApplied with what you actually found.\n` +
      `- Drop nothing silently: every correction above appears in either \`applied\` or \`notApplied\`, with a reason.\n` +
      `- If you change anything outside the authorized field list, report it in \`touchedOutsideAuthorization\`. Concealing it is worse than the edit.\n` +
      `- Do NOT commit or push to the default branch, do NOT open a PR, do NOT merge a PR. Leave the changes in the working tree for a human to review.`,
    { label: 'write:state', phase: 'Write', schema: WRITE_SCHEMA, effort: 'high' }
  )
  // A writer that returned nothing may have written some, all, or none of it. That is lost
  // coverage of the working tree itself, so it lands in `lost` and the run is INCOMPLETE —
  // "wrote: null" must never be read as "wrote nothing".
  if (!wrote) lost.push({ side: 'write', label: 'writer', reason: 'write agent returned no report — the files may be partially edited; inspect the working tree by hand before trusting it' })
}

// Shared recipe contract: every recipe returns `verdict`, and INCOMPLETE is reserved across
// all of them for "an agent died, so this is not a complete judgement". INCOMPLETE outranks
// both domain verdicts here, because the specific way this recipe fails — one missing
// picture — is indistinguishable by shape from perfect agreement. Computed in code, never
// asked of an agent, so a dead reporter cannot upgrade it to something more comfortable.
const verdict = lost.length ? 'INCOMPLETE' : drift.length ? 'DRIFTED' : 'ALIGNED'
log(`state-reconcile: ${verdict} — ${drift.length} drift item(s) on ${SUBJECT}${wrote ? `, ${(wrote.applied || []).length} correction(s) applied` : ''}${lost.length ? `, ${lost.length} STAGE(S) LOST` : ''}`)
return {
  timestamp: A.timestamp,
  asOf: AS_OF,
  subject: SUBJECT,
  verdict,
  summary: rec.summary || '',
  drift,
  driftCount: drift.length,
  claimAhead: drift.filter((d) => d.direction === 'claim-ahead'),
  claimedOnly: rec.claimedOnly || [],
  realityOnly: rec.realityOnly || [],
  unreadable,
  mode: ALLOWED.length ? 'write-back' : 'report-only',
  authorizedFields: ALLOWED,
  withheld,
  wrote: wrote || null,
  lost,
  nextStep: ALLOWED.length
    ? 'Human reviews the working tree — `withheld` and anything in `lost` first — then decides on the commit.'
    : 'Report-only run: nothing was written. Authorize specific fields via args.writeBack.fields to apply corrections.',
}
