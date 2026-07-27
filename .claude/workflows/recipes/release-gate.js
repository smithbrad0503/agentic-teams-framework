export const meta = {
  name: 'release-gate',
  description: 'Decide whether a build is shippable: a strictly serial exclusive-resource chain runs alongside parallel static checks, then the packaged artifact is smoke-launched against a required-evidence list.',
  phases: [
    { title: 'Gates', detail: 'the exclusive chain (serial) fans out alongside the independent static checks' },
    { title: 'Smoke', detail: 'launch the artifact; every required-evidence item reported individually' },
    { title: 'Verdict', detail: 'SHIP / NO-SHIP / INCOMPLETE' },
  ],
}

// ---- args contract -------------------------------------------------------
// {
//   staticChecks: [{ name: 'secrets-scan', instructions: '…' }, …],  // required, non-empty; independent, run in parallel
//   exclusiveChain: [{ name: 'unit-tests', instructions: '…' }, …],  // optional; STRICTLY serial — never concurrent with each other
//   artifactSmoke: { instructions: '…', requiredEvidence: ['exit code 0', …] },  // optional
//   timestamp: '2026-01-01T10:30:00-05:00',  // dispatcher-generated (no Date in scripts)
// }
//
// exclusiveChain is for a machine-level resource that file isolation cannot partition: a
// whole-project build lock, one emulator or physical device, a single licence seat, an
// exclusive test database, a deploy slot. Worktrees isolate files; they do nothing for those.
//
// Two static checks worth passing on almost any project. These are EXAMPLES for the caller
// to copy into args — nothing here is hardcoded behaviour:
//
//   { name: 'secrets-scan',
//     instructions: 'Grep the commit range being gated for API keys, tokens, private keys and
//                    .env values, and confirm nothing under the private/ignored directories is
//                    tracked by git. pass=false on any hit you cannot prove is a test fixture.' }
//
//   { name: 'docs-freshness',
//     instructions: 'List the docs that describe code touched in the range being gated, then read
//                    each one against the current code. Every claim that no longer holds — a
//                    feature described as unfinished after it shipped, a flag or command that was
//                    renamed, a config table that drifted — is an issue. pass=false if any doc
//                    describing changed code was not itself updated.' }
let A = args || {}
if (typeof A === 'string') {
  try {
    A = JSON.parse(A)
  } catch (e) {
    return { error: 'release-gate: args arrived as an unparseable string — pass a JSON object' }
  }
}
if (!Array.isArray(A.staticChecks) || !A.staticChecks.length) {
  return { error: 'release-gate: args.staticChecks must be a non-empty array of {name, instructions}' }
}
if (A.exclusiveChain !== undefined && !Array.isArray(A.exclusiveChain)) {
  return { error: 'release-gate: args.exclusiveChain must be an array of {name, instructions} when present' }
}
if (A.artifactSmoke && (!Array.isArray(A.artifactSmoke.requiredEvidence) || !A.artifactSmoke.requiredEvidence.length)) {
  return { error: 'release-gate: args.artifactSmoke.requiredEvidence must be a non-empty array — a smoke stage with nothing to prove is worthless' }
}

const GATE_SCHEMA = {
  type: 'object',
  properties: {
    pass: { type: 'boolean' },
    summary: { type: 'string', description: 'one line of evidence (≤300 chars, single line)' },
    issues: { type: 'array', items: { type: 'string', description: 'one line, ≤300 chars' } },
  },
  required: ['pass', 'summary', 'issues'],
}
const SMOKE_SCHEMA = {
  type: 'object',
  properties: {
    summary: { type: 'string', description: 'one line, ≤300 chars' },
    evidence: {
      type: 'array',
      description: 'exactly one entry per required-evidence item, requirement copied VERBATIM',
      items: {
        type: 'object',
        properties: {
          requirement: { type: 'string', description: 'the required-evidence item, copied verbatim' },
          met: { type: 'boolean' },
          observed: { type: 'string', description: 'what was actually observed — one line, ≤300 chars' },
        },
        required: ['requirement', 'met', 'observed'],
      },
    },
  },
  required: ['summary', 'evidence'],
}

const CHAIN = A.exclusiveChain || []

// Three statuses, and the third one is the point of this recipe. A gate agent that returned
// null did not FAIL — it never ran, and a release decision that cannot tell "we checked and
// it is broken" from "we never checked" is the failure mode `audit.js` was just patched for.
// Reporting NO-SHIP for an un-run gate is merely misleading; reporting SHIP would be
// catastrophic. So `unrun` is first-class here and never collapses into pass or fail.
const toGate = (name, r) =>
  r
    ? {
        name,
        status: r.pass ? 'pass' : 'fail',
        summary: r.summary || 'gate reported no summary',
        issues: Array.isArray(r.issues) ? r.issues : [],
      }
    : {
        name,
        status: 'unrun',
        summary: 'gate agent returned no report — this gate NEVER RAN, so nothing about it is known',
        issues: [],
      }

// The exclusive chain is ONE element of the parallel() array below — it is deliberately not
// mapped over its own items into a nested parallel(), because its whole contract is that
// nothing in it may be in flight beside anything else in it. The for-await loop is what
// enforces that: each link cannot be dispatched until the previous one has resolved.
// Independent work still fans out around it, which is the only correct way to use a
// machine-level resource under fan-out.
const runExclusiveChain = async () => {
  const gates = []
  let stopped = ''
  for (const step of CHAIN) {
    if (stopped) {
      // Not "unrun": we know exactly why this never ran, and the run is already non-shippable.
      // Blocking is honest bookkeeping, not lost coverage — but it still cannot yield SHIP.
      gates.push({
        name: `chain:${step.name}`,
        status: 'blocked',
        summary: `not attempted — "${stopped}" did not pass earlier in the serial chain`,
        issues: [],
      })
      continue
    }
    const r = await agent(
      `Release gate "${step.name}". You hold an EXCLUSIVE machine-level resource for this step (a build lock, a device, an exclusive database — whatever this project's chain serializes). Do the work yourself, in this one agent: do NOT fan out, do NOT start background jobs that outlive you, and release/close anything you opened before returning.\n\n${step.instructions}\n\nREAD-ONLY except for build artifacts this step is explicitly told to produce. Fix NOTHING. Return pass=true only if the gate genuinely passes; summary = one line of evidence; issues = one line per concrete blocker.`,
      { label: `chain:${step.name}`, phase: 'Gates', schema: GATE_SCHEMA }
    )
    const g = toGate(`chain:${step.name}`, r)
    gates.push(g)
    if (g.status !== 'pass') stopped = step.name
  }
  return gates
}

phase('Gates')
const [chainGates, ...staticGates] = await parallel([
  runExclusiveChain,
  ...A.staticChecks.map((c) => () =>
    agent(
      `Release gate "${c.name}". This check needs no exclusive resource — it runs alongside other gates.\n\n${c.instructions}\n\nREAD-ONLY: run commands and read files to verify, but change NOTHING and deploy NOTHING. Return pass=true only if the gate genuinely passes; summary = one line of evidence; issues = one line per concrete blocker.`,
      { label: `static:${c.name}`, phase: 'Gates', schema: GATE_SCHEMA }
    ).then((r) => toGate(`static:${c.name}`, r))
  ),
])

// A thunk that threw resolves to null. Recovering those as `unrun` (not `fail`) is the same
// rule as above: the whole chain vanishing is maximal loss of coverage, never a clean fail.
const gates = [
  ...(chainGates || CHAIN.map((s) => toGate(`chain:${s.name}`, null))),
  ...staticGates.map((g, i) => g || toGate(`static:${A.staticChecks[i].name}`, null)),
]

// ---- artifact smoke ------------------------------------------------------
// Build ≠ boots. This stage encodes a defect class CI cannot catch by construction: whether
// the thing you are about to hand someone actually starts and is populated. Every
// requiredEvidence item is reconciled INDIVIDUALLY below — a smoke agent that returns a vague
// "looks fine" is worthless, and one that quietly skips a requirement must not read as a pass.
const REQUIRED = (A.artifactSmoke && A.artifactSmoke.requiredEvidence) || []
let evidence = []
if (A.artifactSmoke) {
  phase('Smoke')
  if (gates.some((g) => g.status !== 'pass')) {
    gates.push({
      name: 'artifact-smoke',
      status: 'blocked',
      summary: 'not attempted — an earlier gate did not pass, so the artifact under test is not trustworthy',
      issues: [],
    })
  } else {
    const smoke = await agent(
      `Smoke-launch the PACKAGED artifact this release is about to ship and prove it actually starts and is populated. A build that compiles is not a build that boots.\n\n${A.artifactSmoke.instructions}\n\nYou must report on EVERY one of these required-evidence items, individually, copying each requirement VERBATIM into the requirement field:\n${REQUIRED.map((e, i) => `${i + 1}. ${e}`).join('\n')}\n\nFor each: met=true only if you directly observed it, and observed = the concrete thing you saw (the exit code, the log line, the count). Never mark an item met because the run "looked fine". If you could not check an item, report it with met=false and say so in observed. Clean up anything you launched.`,
      { label: 'artifact-smoke', phase: 'Smoke', schema: SMOKE_SCHEMA }
    )
    const reported = (smoke && Array.isArray(smoke.evidence) ? smoke.evidence : []).filter(Boolean)
    evidence = REQUIRED.map((req) => {
      const hit = reported.find((e) => e.requirement === req)
      return hit
        ? { requirement: req, met: !!hit.met, observed: hit.observed || 'no observation given', reported: true }
        : { requirement: req, met: false, observed: 'the smoke agent never reported on this requirement', reported: false }
    })
    const unreported = evidence.filter((e) => !e.reported)
    const unmet = evidence.filter((e) => e.reported && !e.met)
    gates.push({
      name: 'artifact-smoke',
      // An unreported requirement is un-run coverage, not a failed assertion — same rule as a
      // dead gate agent. Only evidence the agent actually looked at can be called a failure.
      status: !smoke || unreported.length ? 'unrun' : unmet.length ? 'fail' : 'pass',
      summary: (smoke && smoke.summary) || 'smoke agent returned no report — the artifact was NEVER LAUNCHED',
      issues: [
        ...unmet.map((e) => `evidence not met: ${e.requirement} — observed: ${e.observed}`),
        ...unreported.map((e) => `evidence NEVER CHECKED: ${e.requirement}`),
      ],
      evidence,
    })
  }
}

phase('Verdict')
const unrun = gates.filter((g) => g.status === 'unrun')
const failed = gates.filter((g) => g.status === 'fail')
// Precedence: INCOMPLETE outranks NO-SHIP, and never degrades into it. NO-SHIP is a COMPLETE
// judgement — it asserts we evaluated this build and it is broken. A run with an un-run gate
// is not entitled to any complete judgement, and calling it NO-SHIP invites "fix that one
// failure and ship", which is exactly the path that must never open. Nothing is lost either
// way: `failed` and `unrun` are both returned, so the caller sees both facts whichever the
// verdict string says. SHIP requires every single gate green — `blocked` gates cannot yield it.
const verdict = unrun.length ? 'INCOMPLETE' : failed.length ? 'NO-SHIP' : gates.every((g) => g.status === 'pass') ? 'SHIP' : 'NO-SHIP'
log(`release-gate: ${verdict} — ${gates.filter((g) => g.status === 'pass').length}/${gates.length} gates green${failed.length ? `, ${failed.length} failed` : ''}${unrun.length ? `, ${unrun.length} NEVER RAN (re-run the gate; this build was not evaluated)` : ''}`)

// The report agent writes prose only. The verdict above is computed in code, so a dead
// reporter cannot turn an INCOMPLETE into anything else.
const report = await agent(
  `Write the release go/no-go report. The verdict is already decided — it is ${verdict} — and you may not change it.\n\nGate results:\n${JSON.stringify(gates, null, 2)}\n\nLead with the verdict. For each failed gate give the concrete blocker and the one-line fix path. For each gate that NEVER RAN, say plainly that this build was not evaluated on that gate and that re-running is required — do not describe it as a failure or as a pass. Invent no results.`,
  { label: 'verdict', phase: 'Verdict' }
)

return {
  timestamp: A.timestamp || '',
  verdict,
  shippable: verdict === 'SHIP',
  gates,
  failed,
  unrun,
  evidence,
  report: report || '(report agent returned nothing — the verdict above is computed in code and stands)',
}
