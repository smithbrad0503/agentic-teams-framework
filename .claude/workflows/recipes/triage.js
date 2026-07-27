export const meta = {
  name: 'triage',
  description: 'Turn an unstructured human report into diagnosed, deduped, prioritized work. Read-only — diagnoses code, never changes it.',
  phases: [
    { title: 'Split', detail: 'raw report → atomic items, reporter wording preserved' },
    { title: 'Diagnose', detail: 'one read-only agent per item, root cause at file:line' },
    { title: 'Consolidate', detail: 'dedupe by root cause → fixNow / decisionsNeeded / questionsBack / protect' },
  ],
}

// ---- args contract -------------------------------------------------------
// {
//   report: 'everything wrong with the app' | ['…', '…'],   // required, any shape
//   context: 'what this project is, for the diagnosing agents',
//   categories: ['BUG','UX','DESIGN','DATA','PERF','UNCLEAR'],
//   severities: ['BLOCKS_CORE_FLOW','DEGRADES','POLISH','NICE_TO_HAVE'],
//   trackedDebt: ['known issue …'],   // must NOT be re-diagnosed as new work
//   timestamp: '2026-01-01T10:30:00-05:00',
// }
// The output is shaped to be pasted straight into `/team dispatch` briefs.
let A = args || {}
if (typeof A === 'string') {
  try {
    A = JSON.parse(A)
  } catch (e) {
    return { error: 'triage: args arrived as an unparseable string — pass a JSON object' }
  }
}
if (!A.report || (Array.isArray(A.report) && !A.report.length)) {
  return { error: 'triage: args.report is required (a string or non-empty string[] of raw human feedback)' }
}

const CATEGORIES = Array.isArray(A.categories) && A.categories.length ? A.categories : ['BUG', 'UX', 'DESIGN', 'DATA', 'PERF', 'UNCLEAR']
const SEVERITIES = Array.isArray(A.severities) && A.severities.length ? A.severities : ['BLOCKS_CORE_FLOW', 'DEGRADES', 'POLISH', 'NICE_TO_HAVE']
const TRACKED = Array.isArray(A.trackedDebt) ? A.trackedDebt.filter(Boolean) : []
const UNKNOWN_KIND = CATEGORIES.indexOf('UNCLEAR') >= 0 ? 'UNCLEAR' : CATEGORIES[CATEGORIES.length - 1]
const KEEP_SEVERITY = SEVERITIES[SEVERITIES.length - 1]
const raw = Array.isArray(A.report) ? A.report.join('\n') : String(A.report)
const CONTEXT = `Project context: ${A.context || '(none supplied — read the repo to work out what this project is before judging anything)'}` +
  (TRACKED.length ? `\nAlready-tracked known issues — do NOT re-diagnose these as new work; set alreadyTracked=true and move on:\n${TRACKED.map((d) => `- ${d}`).join('\n')}` : '')

const SPLIT_SCHEMA = {
  type: 'object',
  properties: {
    items: { type: 'array', items: { type: 'string', description: 'one atomic observation in the reporter’s own words' } },
  },
  required: ['items'],
}
const DIAGNOSIS_SCHEMA = {
  type: 'object',
  properties: {
    kind: { type: 'string', enum: CATEGORIES },
    severity: { type: 'string', enum: SEVERITIES },
    rootCause: { type: 'string', description: 'the most likely cause, citing file:line where findable' },
    proposedFix: { type: 'string', description: 'the smallest real fix' },
    effort: { type: 'string', enum: ['S', 'M', 'L'] },
    needsHumanDecision: { type: 'boolean', description: 'true if the fix changes product direction, not just implementation' },
    alreadyTracked: { type: 'boolean', description: 'true if this matches a known issue listed in the context' },
  },
  required: ['kind', 'severity', 'rootCause', 'proposedFix', 'effort', 'needsHumanDecision'],
}
const PLAN_SCHEMA = {
  type: 'object',
  properties: {
    fixNow: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          title: { type: 'string', description: 'one line, usable as a /team dispatch brief title' },
          rootCause: { type: 'string', description: 'file:line' },
          fix: { type: 'string' },
          effort: { type: 'string', enum: ['S', 'M', 'L'] },
          severity: { type: 'string', enum: SEVERITIES },
          symptoms: { type: 'array', items: { type: 'string' }, description: 'every reported item sharing this root cause' },
        },
        required: ['title', 'rootCause', 'fix', 'effort', 'severity'],
      },
    },
    decisionsNeeded: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          question: { type: 'string', description: 'the decision, one line' },
          recommendation: { type: 'string', description: 'THE recommendation — one course of action, not a menu of options' },
          why: { type: 'string', description: 'one line of reasoning for that recommendation' },
          rootCause: { type: 'string' },
        },
        required: ['question', 'recommendation', 'why'],
      },
    },
    questionsBack: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          item: { type: 'string' },
          question: { type: 'string', description: 'what to ask the reporter to make this actionable' },
        },
        required: ['item', 'question'],
      },
    },
    protect: { type: 'array', items: { type: 'string' }, description: 'behaviour the reporter asked us NOT to change' },
  },
  required: ['fixNow', 'decisionsNeeded', 'questionsBack', 'protect'],
}

phase('Split')
const split = await agent(
  `${CONTEXT}\n\nRaw report from a human:\n"""${raw}"""\n\n` +
    `READ-ONLY: you may read files to understand a reference, but change NOTHING — this is a triage pass, not a fix.\n\n` +
    `Split this into atomic items, one observation each, PRESERVING the reporter's wording plus whatever context each item needs to stand alone. ` +
    `Do not editorialize, merge, or reclassify — a later stage diagnoses; you only cut. ` +
    `Drop pure praise UNLESS it signals "keep this behaviour, don't change it", in which case keep it prefixed [KEEP].`,
  { label: 'split-report', phase: 'Split', schema: SPLIT_SCHEMA }
)
if (!split || !Array.isArray(split.items) || !split.items.length) {
  // A dead splitter is not an empty report. Falling through with zero items would
  // return four empty lists — a clean bill of health for a report nobody read.
  // The raw text comes back as undiagnosed instead, so nothing the human said is lost.
  log('triage: split agent returned no items — report surfaced undiagnosed')
  return {
    timestamp: A.timestamp || '',
    error: 'triage: split agent returned no items — the report was never read',
    verdict: 'INCOMPLETE',
    complete: false,
    itemCount: 0,
    diagnosed: [],
    undiagnosed: [{ item: raw, reason: 'split agent returned no report; no diagnosis ran' }],
    fixNow: [],
    decisionsNeeded: [],
    questionsBack: [],
    protect: [],
  }
}
const items = split.items.map((i) => String(i))
// The protect list is derived here as well as asked of the planner: an item the
// reporter marked "don't change this" must survive even if the planner drops it.
// Silently reclassifying "I like this" as a bug is worse than no triage at all.
const keeps = items.filter((i) => i.indexOf('[KEEP]') === 0)
log(`triage: ${items.length} atomic item(s), ${keeps.length} [KEEP]`)

phase('Diagnose')
const diagnosed = await pipeline(items, (item, _orig, i) =>
  agent(
    `${CONTEXT}\n\nDiagnose this single reported item by actually reading the relevant code:\n"""${item}"""\n\n` +
      `READ-ONLY: read code, config and history, change NOTHING and commit NOTHING. Diagnosis only — someone else fixes it.\n\n` +
      `Find the most likely root cause and cite it as file:line. Classify kind (${CATEGORIES.join('|')}) and severity (${SEVERITIES.join('|')}). ` +
      `Propose the smallest real fix and size it S (<1h), M (one focused pass), L (multi-pass). ` +
      `Set needsHumanDecision=true when the fix changes product direction rather than implementation. ` +
      `If it matches a known tracked issue above, set alreadyTracked=true and say so in rootCause instead of writing it up as new. ` +
      `If the item is prefixed [KEEP], do not treat it as a defect: severity=${KEEP_SEVERITY}, proposedFix="protect: <what must not regress>". ` +
      `If you genuinely cannot locate it, use kind=${UNKNOWN_KIND} and put the question for the reporter in proposedFix.`,
    { label: `diagnose:${i + 1}`, phase: 'Diagnose', schema: DIAGNOSIS_SCHEMA }
  ).then((d) => (d ? { item, ...d } : { item, undiagnosed: true, reason: 'diagnosing agent returned no report' }))
)
// A thunk that threw resolves to null and would vanish from the report entirely —
// the same failure the `.then` above covers, one layer out. Recovered, never filtered.
const settled = diagnosed.map((d, i) => d || { item: items[i] || '(item lost)', undiagnosed: true, reason: 'diagnosing agent errored before returning' })
const good = settled.filter((d) => !d.undiagnosed)
const undiagnosed = settled.filter((d) => d.undiagnosed)

phase('Consolidate')
const plan = await agent(
  `${CONTEXT}\n\nDiagnosed items:\n${JSON.stringify(good, null, 2)}\n\n` +
    (undiagnosed.length
      ? `COVERAGE WAS PARTIAL: ${undiagnosed.length} of ${items.length} item(s) could not be diagnosed (their agents failed). Do not describe this triage as complete.\n\n`
      : '') +
    `READ-ONLY: you may read code to confirm two symptoms share one cause, but change NOTHING.\n\n` +
    `Consolidate into four lists:\n` +
    `1. fixNow — work we can dispatch without asking anyone. MERGE items that share a root cause into one entry and list the merged symptoms; several reported symptoms usually have one cause. Order by severity, then by effort so quick wins land early. Each entry must read as a /team dispatch brief on its own.\n` +
    `2. decisionsNeeded — anything with needsHumanDecision=true. Each entry carries THE recommendation: one course of action you would take, plus one line of why. Never an option menu — "you could do A or B" moves the work back to the human instead of doing it.\n` +
    `3. questionsBack — items you could not pin down, with the specific question to ask the reporter.\n` +
    `4. protect — every [KEEP] item, stated as what must not regress.\n\n` +
    `Items marked alreadyTracked belong in none of these as new work; mention them once inside the relevant fixNow entry if they matter. Plain language, lead with what matters.`,
  { label: 'consolidate', phase: 'Consolidate', schema: PLAN_SCHEMA }
)
// The union keeps a planner-dropped [KEEP] on the protect list — the protect list
// is the one output that must never shrink, whatever the agents did.
const planned = plan && Array.isArray(plan.protect) ? plan.protect : []
const protect = planned.concat(keeps.filter((k) => !planned.some((p) => String(p).indexOf(k.slice(0, 40)) >= 0)))
if (!plan) {
  log(`triage: consolidator returned no report — ${good.length} diagnosis/es returned raw`)
  return {
    timestamp: A.timestamp || '',
    error: 'triage: consolidate agent returned no report — diagnoses returned unconsolidated',
    verdict: 'INCOMPLETE',
    complete: false,
    itemCount: items.length,
    diagnosed: good,
    undiagnosed,
    fixNow: [],
    decisionsNeeded: [],
    questionsBack: [],
    protect,
  }
}
log(`triage: ${(plan.fixNow || []).length} to fix, ${(plan.decisionsNeeded || []).length} decision(s), ${(plan.questionsBack || []).length} question(s), ${protect.length} protected${undiagnosed.length ? `, ${undiagnosed.length} UNDIAGNOSED (agent failed — triage these by hand)` : ''}`)
// Shared recipe contract: every recipe returns `verdict`, and INCOMPLETE is reserved
// across all of them for "an agent died, so this is not a complete judgement". `complete`
// stays for callers already reading it, but `verdict` is the field that works without
// knowing which recipe produced the result.
return {
  timestamp: A.timestamp || '',
  verdict: undiagnosed.length ? 'INCOMPLETE' : 'TRIAGED',
  complete: undiagnosed.length === 0,
  itemCount: items.length,
  diagnosed: good,
  undiagnosed,
  fixNow: plan.fixNow || [],
  decisionsNeeded: plan.decisionsNeeded || [],
  questionsBack: plan.questionsBack || [],
  protect,
}
