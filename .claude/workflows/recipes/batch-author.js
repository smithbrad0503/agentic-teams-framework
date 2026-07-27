export const meta = {
  name: 'batch-author',
  description: 'Author N entries that all land in the SAME file: parallel read-only authors, then one serialized writer.',
  phases: [
    { title: 'Survey', detail: 'one read-only agent writes the authoring spec: files, schema, exemplar, invariants, validating commands' },
    { title: 'Author', detail: 'one read-only agent per target, returning a structured entry' },
    { title: 'Validate', detail: 'per-entry check against the surveyed invariants; repairs in place when it can' },
    { title: 'Write', detail: 'exactly ONE writer merges every entry and commits once' },
    { title: 'Verify', detail: 'run the validating commands the survey identified' },
  ],
}

// ---- args contract -------------------------------------------------------
// {
//   kind: 'i18n string',                            // what is being authored, one entry per target
//   targets: [{ name: 'checkout.title', brief: 'header on the checkout page' }, …],
//   surveyInstructions: 'the catalog lives in locales/*.json; the loader is …',
//   branch: 'feature/i18n-checkout',                // where the writer commits
//   groupBy: 'locale',                              // optional target field: writers run serially, one group at a time
//   timestamp: '2026-01-01T10:30:00-05:00',
// }
//
// Reach for this when N independent work items all mutate ONE file — an i18n
// catalog, a seed/fixture dataset, a config registry, an OpenAPI spec, a docs
// index, a route table. Neither worktree isolation (which isolates whole runs)
// nor directory-shaped ownership zones can express that shape: the items are
// independent to THINK about and contended to WRITE. So: parallelize the
// thinking, serialize the writing.
let A = args || {}
if (typeof A === 'string') {
  try {
    A = JSON.parse(A)
  } catch (e) {
    return { error: 'batch-author: args arrived as an unparseable string — pass a JSON object' }
  }
}
if (!A.kind || !Array.isArray(A.targets) || !A.targets.length || !A.surveyInstructions) {
  return { error: 'batch-author: args.kind, a non-empty args.targets ([{name, brief}]), and args.surveyInstructions are required' }
}

const BRANCH = A.branch || ''
const ALL = '(all)'
const groupOf = (t) => (A.groupBy && t && t[A.groupBy] != null ? String(t[A.groupBy]) : ALL)

const SPEC_SCHEMA = {
  type: 'object',
  properties: {
    targetFiles: { type: 'array', items: { type: 'string' }, description: 'every file one new entry must touch' },
    entrySchema: { type: 'string', description: 'the exact field-by-field schema of one entry' },
    exemplar: { type: 'string', description: 'ONE real existing entry, copied verbatim — never invented' },
    invariants: {
      type: 'array',
      items: { type: 'string' },
      description: 'constraints existing entries already satisfy, each stated WITH evidence from real rows (ranges, formats, cross-references, ordering, uniqueness)',
    },
    validateCommands: { type: 'array', items: { type: 'string' }, description: 'commands/tests that validate these files after an edit' },
  },
  required: ['targetFiles', 'entrySchema', 'exemplar', 'invariants', 'validateCommands'],
}
const ENTRY_SCHEMA = {
  type: 'object',
  properties: {
    name: { type: 'string' },
    content: { type: 'string', description: 'the exact text to add, as {"<file path>": "<literal text to insert>"} JSON text' },
    rationale: { type: 'string', description: 'one line, ≤300 chars' },
    assumptions: { type: 'array', items: { type: 'string' }, description: 'anything the author had to guess, one line each' },
  },
  required: ['name', 'content'],
}
const VALIDATION_SCHEMA = {
  type: 'object',
  properties: {
    valid: { type: 'boolean' },
    violations: { type: 'array', items: { type: 'string' }, description: 'which surveyed invariant is broken and how, one line each' },
    fixedEntry: { type: 'string', description: 'the corrected entry as JSON text when the violations were mechanically fixable; empty string otherwise' },
  },
  required: ['valid', 'violations'],
}
const WRITE_SCHEMA = {
  type: 'object',
  properties: {
    filesChanged: { type: 'array', items: { type: 'string' } },
    commit: { type: 'string', description: 'the single commit hash' },
    merged: { type: 'array', items: { type: 'string' }, description: 'entry names actually written' },
    notMerged: { type: 'array', items: { type: 'string' }, description: 'entry name + reason for anything not written — never omit one silently' },
  },
  required: ['filesChanged', 'merged', 'notMerged'],
}
const VERIFY_SCHEMA = {
  type: 'object',
  properties: {
    passed: { type: 'boolean' },
    results: { type: 'array', items: { type: 'string' }, description: 'one line per command: the command and its verbatim outcome' },
    missingEntries: { type: 'array', items: { type: 'string' }, description: 'entry names the writer claimed but that are not in the files' },
  },
  required: ['passed', 'results', 'missingEntries'],
}

phase('Survey')
const spec = await agent(
  `Survey how "${A.kind}" entries are defined in this repo, end to end.\n\n${A.surveyInstructions}\n\nREAD-ONLY: read files and run read-only commands, change NOTHING.\n\nProduce an authoring spec another agent can follow BLIND — it will never see this repo:\n- targetFiles: every file one new entry must touch\n- entrySchema: the exact field-by-field schema\n- exemplar: ONE real existing entry copied verbatim (do not invent it)\n- invariants: the constraints existing entries already satisfy that a new one must not violate, each stated WITH evidence drawn from real rows — value ranges (min/median/max of the key numbers), id/key formats, required cross-references, sort order, uniqueness. This is the load-bearing field: it is the only thing between a blind author and a plausible-looking entry that quietly corrupts the file.\n- validateCommands: the exact commands/tests that validate these files after an edit`,
  { label: `survey:${String(A.kind).slice(0, 40)}`, phase: 'Survey', schema: SPEC_SCHEMA, effort: 'high' }
)
if (!spec) {
  return { error: 'batch-author: survey agent returned no spec — authors cannot work blind, so nothing was authored and nothing was written' }
}
const SPEC = JSON.stringify(spec, null, 2)

phase('Author')
const worked = await pipeline(
  A.targets,
  (t) =>
    agent(
      `Author ONE ${A.kind} entry named "${(t && t.name) || ''}".\nBrief: ${(t && t.brief) || '(none given)'}\n\nAuthoring spec:\n${SPEC}\n\nREAD-ONLY: read files for reference, but DO NOT write, edit, create, move or delete any file, and do not run git. A single later stage merges every entry — concurrent writers to these shared files would conflict and lose work.\n\nReturn the complete entry: the exact text per target file, matching the schema and the exemplar's formatting, satisfying EVERY invariant in the spec. State anything you had to assume.`,
      { label: `author:${String((t && t.name) || 'target').slice(0, 40)}`, phase: 'Author', schema: ENTRY_SCHEMA }
    ),
  (draft, t, i) => {
    const item = t || A.targets[i] || {}
    const name = String(item.name || `target-${i + 1}`)
    // An author that DIED did not author an empty entry. Returning null here would
    // let this target vanish from `worked`, and a batch that authors 7 of 10 and
    // reports success is the worst outcome available: the gap is invisible. Every
    // branch below returns an outcome object carrying a status.
    if (!draft) return { name, group: groupOf(item), status: 'failed', issues: ['author agent returned no entry'], entry: null }
    return agent(
      `Validate ONE authored ${A.kind} entry against the surveyed invariants.\n\nAuthoring spec (invariants are the contract):\n${SPEC}\n\nEntry:\n${JSON.stringify(draft, null, 2)}\n\nREAD-ONLY: change no file. Check every invariant in the spec, plus schema conformance, formatting/ordering against the exemplar, key uniqueness against existing entries, and any cross-reference the entry claims. If the violations are mechanically fixable (a key, a number, a format), return the whole corrected entry in fixedEntry; otherwise report them and leave fixedEntry empty.`,
      { label: `validate:${name.slice(0, 40)}`, phase: 'Validate', schema: VALIDATION_SCHEMA }
    ).then((v) => {
      // Same discipline one stage down: a validator that died did not approve the
      // entry and did not reject it — it never ran. That is its own status, so a
      // never-checked entry can never be reported as a checked one.
      if (!v) return { name, group: groupOf(item), status: 'unvalidated', issues: ['validator agent returned no report — the invariants were never checked'], entry: draft }
      let entry = draft
      if (v.fixedEntry) {
        try {
          entry = JSON.parse(v.fixedEntry)
        } catch (e) {
          entry = draft
        }
      }
      const repaired = entry !== draft
      const violations = v.violations && v.violations.length ? v.violations : ['validator reported invalid with no detail']
      if (!v.valid && !repaired) return { name, group: groupOf(item), status: 'rejected', issues: violations, entry: draft }
      return { name, group: groupOf(item), status: repaired ? 'repaired' : 'ok', issues: repaired ? violations : [], entry }
    })
  }
)

// Index-aligned recovery. `pipeline` preserves target order and yields null where a
// stage thunk threw outright; `.filter(Boolean)` over this array is exactly how a
// target disappears without a trace, so every index is mapped back to its target.
const outcomes = A.targets.map((t, i) => {
  const o = worked && worked[i]
  return o || { name: String((t && t.name) || `target-${i + 1}`), group: groupOf(t), status: 'failed', issues: ['authoring stage errored — no result returned for this target'], entry: null }
})
const writable = outcomes.filter((o) => o.entry && o.status !== 'failed' && o.status !== 'rejected')
const failed = outcomes.filter((o) => o.status === 'failed' || o.status === 'rejected')
const unvalidated = outcomes.filter((o) => o.status === 'unvalidated')
log(`batch-author: ${writable.length}/${A.targets.length} ${A.kind} entries ready to write${failed.length ? `, ${failed.length} FAILED (reported, never dropped)` : ''}${unvalidated.length ? `, ${unvalidated.length} UNVALIDATED` : ''}`)

const outcomeReport = outcomes.map((o) => ({ name: o.name, group: o.group, status: o.status, issues: o.issues }))
if (!writable.length) {
  return {
    timestamp: A.timestamp || '',
    kind: A.kind,
    branch: BRANCH,
    requested: A.targets.length,
    outcomes: outcomeReport,
    failed: failed.map((o) => ({ name: o.name, status: o.status, issues: o.issues })),
    unvalidated: unvalidated.map((o) => ({ name: o.name, issues: o.issues })),
    writes: [],
    verify: { passed: false, results: ['not run — no entry survived authoring, so nothing was written'], missingEntries: [] },
    nextStep: 'Nothing was written. Read `failed` — every requested target is accounted for there — and re-run the ones worth retrying.',
  }
}

phase('Write')
// ---- THE SINGLE-WRITER INVARIANT — do not "optimize" this into a fan-out. -----
// Every entry in this batch lands in the SAME file(s). N agents editing one file
// concurrently produce interleaved, conflicting, or lost edits — that is the entire
// reason the Author stage above is read-only. The parallelism in this recipe lives
// in the Author stage and nowhere else, on purpose.
// With groupBy unset there is exactly ONE group and therefore exactly ONE writer.
// With groupBy set the groups run one at a time, never concurrently — the same
// contention argument applies within a group's files, and the first writer creates
// the branch the rest commit onto. The `await` inside this for-loop is load-bearing:
// it is what makes "serial" true rather than aspirational.
const groups = {}
for (const o of writable) {
  groups[o.group] = groups[o.group] || []
  groups[o.group].push(o)
}
const writes = []
let first = true
for (const key of Object.keys(groups)) {
  const batch = groups[key].map((o) => ({ name: o.name, status: o.status, issues: o.issues, entry: o.entry }))
  const report = await agent(
    `Merge ${batch.length} authored ${A.kind} entries into the repo${key === ALL ? '' : ` — group "${key}" (grouped by ${A.groupBy})`}, in ONE commit.\n\n` +
      `${first ? (BRANCH ? `Create or switch to branch "${BRANCH}" from the default branch.` : 'No branch was given: commit on the CURRENT branch, and if that is the default branch, write nothing and say so.') : `You are already on branch "${BRANCH || '(the current branch)'}" — an earlier writer in this same batch committed there. Do not rebase, do not reset, do not amend their commit.`}\n\n` +
      `Authoring spec — the files, schema, exemplar and invariants to match:\n${SPEC}\n\nEntries:\n${JSON.stringify(batch, null, 2)}\n\n` +
      `You are the ONLY agent writing these files in this run: no other writer is active now, and none will run concurrently with you.\n` +
      `Rules: match the exemplar's formatting and ordering exactly; every file you touch must still parse and lint; entries whose status is "unvalidated" or that carry issues are included ON PURPOSE — merge them and list them in your report so a human can look. Invent nothing. Drop nothing silently: anything you cannot merge goes in notMerged with the reason. Commit exactly once. NEVER commit or push to the default branch, and do NOT open or merge a PR.`,
    { label: `write:${key.slice(0, 40)}`, phase: 'Write', schema: WRITE_SCHEMA, effort: 'high' }
  )
  writes.push({
    group: key,
    ok: !!report,
    entries: batch.map((b) => b.name),
    commit: (report && report.commit) || '',
    filesChanged: (report && report.filesChanged) || [],
    merged: (report && report.merged) || [],
    notMerged: (report && report.notMerged) || [],
    note: report ? '' : 'writer agent returned no report — this group may be partially written; check the branch by hand before trusting it',
  })
  first = false
}

phase('Verify')
const commandList = (spec.validateCommands || []).map((c) => `- ${c}`).join('\n')
const expected = writable.map((o) => o.name).join(', ')
const verify = await agent(
  `Verify the ${A.kind} batch just written${BRANCH ? ` on branch "${BRANCH}"` : ''}.\n\n1. Run exactly these validating commands the survey identified, and report each one's outcome verbatim (one line each):\n${commandList}\n2. Confirm each of these entry names is actually present in the target files: ${expected}\n\nREAD-ONLY: do not fix anything, do not commit, do not push. Failing commands and missing entries are the point of this stage — report them, do not repair them.`,
  { label: 'verify', phase: 'Verify', schema: VERIFY_SCHEMA }
)
const writeFailures = writes.filter((w) => !w.ok)
log(`batch-author: ${writes.length} write group(s), ${writeFailures.length} with no report; verify ${verify ? (verify.passed ? 'passed' : 'FAILED') : 'UNKNOWN (verifier returned no report)'}`)

// Shared recipe contract: every recipe returns `verdict`, and INCOMPLETE is reserved
// across all of them for "an agent died, so this is not a complete judgement". A batch
// that authored 7 of 10 and reported success is the worst outcome here, because the gap
// is invisible — so a dead author, a dead validator, or a dead verifier all land here.
const incompleteRun = failed.length || unvalidated.length || writeFailures.length || !verify
return {
  timestamp: A.timestamp || '',
  verdict: incompleteRun ? 'INCOMPLETE' : verify.passed ? 'AUTHORED' : 'REJECTED',
  kind: A.kind,
  branch: BRANCH,
  requested: A.targets.length,
  outcomes: outcomeReport,
  failed: failed.map((o) => ({ name: o.name, status: o.status, issues: o.issues })),
  unvalidated: unvalidated.map((o) => ({ name: o.name, issues: o.issues })),
  writes,
  verify: verify || { passed: false, results: ['verify agent returned no report — this batch is UNVERIFIED, not verified-clean'], missingEntries: [] },
  nextStep: 'Human reviews the branch — `failed`, `unvalidated`, and any write group with ok=false first — then decides on the PR.',
}
