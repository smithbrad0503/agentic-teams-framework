export const meta = {
  name: 'landscape-check',
  description: 'Check whether the surrounding ecosystem has started providing capabilities this project still maintains itself, verifying each apparent overlap by what it DOES rather than by what it is called. Read-only — reports what to stop maintaining and what is still genuinely ours, and edits nothing.',
  phases: [
    { title: 'Probe', detail: 'one read-only probe per capability: search every named surface for something that already covers it, citing concrete artifacts only' },
    { title: 'Verify', detail: 'each candidate compared function by function against what our capability actually does — a shared name is not a shared job' },
  ],
}

// ---- args contract -------------------------------------------------------
// {
//   capabilities: [                              // required, non-empty — what WE maintain
//     {
//       name: 'skill authoring workflow',
//       whatItDoes: 'interviews an author, scaffolds a SKILL.md from a template, validates frontmatter',
//       whereItLives: 'skills/skill-new/',       // optional but strongly wanted: it is what lets
//     },                                         // the verifier judge ours by its source, not its name
//   ],
//   surfaces: [                                  // optional — defaults below, ordered platform-first
//     { key: 'official-extensions', howToCheck: 'run `claude plugin marketplace list` and read each entry' },
//   ],
//   timestamp: '2026-01-01T10:30:00-05:00',      // dispatcher-generated (no wall-clock reads in scripts)
// }
//
// Why this recipe exists: a framework that maintains its own capabilities inside a moving
// ecosystem eventually maintains things the platform now gives away. Every one of those is
// pure cost — maintenance, surface area, and a differentiation claim that is quietly false.
// This already happened here once, found by a human going and looking at a marketplace
// listing; two builds were killed and a third reframed. This makes that check systematic.
let A = args || {}
if (typeof A === 'string') {
  try {
    A = JSON.parse(A)
  } catch (e) {
    return { error: 'landscape-check: args arrived as an unparseable string — pass a JSON object' }
  }
}
if (!Array.isArray(A.capabilities) || !A.capabilities.length) {
  return { error: 'landscape-check: args.capabilities must be a non-empty array of {name, whatItDoes, whereItLives}' }
}
if (A.capabilities.some((c) => !c || !c.name || !c.whatItDoes)) {
  return {
    error:
      'landscape-check: every args.capabilities entry needs at least {name, whatItDoes} — a bare name is precisely what makes a probe and a verifier compare names instead of functions',
  }
}

// Ordered platform-first, and the order is the point. A capability the platform now ships
// natively is subsumed decisively: there is no dependency to take on, no adoption risk, and
// no version to track. The same coverage from a community package is real but costs you a
// third-party dependency, so it is the weakest kind of "stop maintaining this" and is read
// last. Callers override the list; a probe that skips a tier does not know it skipped it.
const DEFAULT_SURFACES = [
  {
    key: 'platform-native',
    howToCheck:
      'the platform or runtime this capability plugs into — its built-in features, native primitives, and the release notes and changelogs of recent versions. Coverage here is the strongest kind: nothing to install, nothing to depend on.',
  },
  {
    key: 'official-extensions',
    howToCheck:
      "the vendor's own official marketplace, plugin registry or first-party extension catalog — list it and read the entries rather than recalling them. Maintained by the platform owner, so adopting one is low-risk.",
  },
  {
    key: 'official-docs',
    howToCheck:
      'official documentation, migration guides and deprecation notices — where a capability is handled as a documented practice or a recommended pattern rather than as a discrete named artifact.',
  },
  {
    key: 'community-ecosystem',
    howToCheck:
      'widely-adopted third-party packages, plugins and open-source projects in this space. Real coverage, but adopting one means taking a dependency — note maintenance activity and abandonment risk alongside the citation.',
  },
]

const surfaces = Array.isArray(A.surfaces) && A.surfaces.length ? A.surfaces : DEFAULT_SURFACES
if (surfaces.some((s) => !s || !s.key || !s.howToCheck)) {
  return { error: 'landscape-check: every args.surfaces entry needs {key, howToCheck} — a bare key tells a probe nothing about where to look' }
}

const surfaceList = surfaces.map((s, i) => `  ${i + 1}. ${s.key} — ${s.howToCheck}`).join('\n')

const CANDIDATES_SCHEMA = {
  type: 'object',
  properties: {
    candidates: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          surface: { type: 'string', description: 'which surface key this was found on' },
          provider: { type: 'string', description: 'the plugin / package / feature name, exactly as the surface spells it' },
          citation: {
            type: 'string',
            description:
              'the concrete artifact you looked at THIS RUN: a registry listing, a doc heading, a file path, a command and what it printed. Never a recollection.',
          },
          whatItProvides: { type: 'string', description: 'one line, ≤300 chars — what it appears to do, in terms of behaviour, not marketing' },
        },
        required: ['surface', 'provider', 'citation', 'whatItProvides'],
      },
    },
    checkedSurfaces: { type: 'array', items: { type: 'string' }, description: 'surface keys you actually checked' },
    notCheckable: {
      type: 'array',
      items: { type: 'string' },
      description: 'surface keys you could NOT check, each with why — an unreachable surface must be said out loud, never guessed at',
    },
  },
  required: ['candidates', 'checkedSurfaces', 'notCheckable'],
}

// `theirs` and `ours` are required and are asked for BEFORE `coverage`: a verifier that has
// to write down what each side actually does, in its own words, cannot answer the question
// from the two names alone. That ordering is the whole defence against name-overlap.
const COMPARISON_SCHEMA = {
  type: 'object',
  properties: {
    theirs: { type: 'string', description: 'what THEIR artifact actually does, established from its docs or source — not from its name' },
    ours: { type: 'string', description: 'what OUR capability actually does, established from its implementation — not from its name' },
    coverage: {
      type: 'string',
      enum: ['full', 'partial', 'none'],
      description: 'full = ours could be deleted; partial = some of the job; none = shares a name or a topic, not the job',
    },
    stillOurs: { type: 'string', description: 'precisely what theirs does NOT do — required even when coverage is full ("nothing" if genuinely nothing)' },
    reason: { type: 'string', description: 'one line, ≤300 chars — cite the behaviour that decided it' },
  },
  required: ['theirs', 'ours', 'coverage', 'stillOurs', 'reason'],
}

const EVIDENCE_RULE = `EVIDENCE, NOT RECOLLECTION. Every candidate must cite a concrete artifact you actually looked at in this run: a plugin or package name as the registry lists it, a documented feature with the heading it sits under, a file path, a read-only command and what it printed. Your prior knowledge of this ecosystem is stale by construction — this recipe exists BECAUSE the ecosystem moved since anything was written about it. "I believe X exists" and "there is probably a plugin for this" are not candidates: report nothing rather than report those. If a surface cannot be checked at all (no such registry here, the command is unavailable, the docs are not reachable), list its key in notCheckable with the reason instead of guessing what it would have contained.`

const probePrompt = (cap) => `Find out whether the surrounding ecosystem ALREADY provides one capability this project maintains itself.

THE CAPABILITY WE MAINTAIN
  name: ${cap.name}
  what it does: ${cap.whatItDoes}
  where it lives: ${cap.whereItLives || '(not stated — locate it in this repo yourself, so you know what you are hunting for an equivalent of)'}

SURFACES TO CHECK, in this order:
${surfaceList}

${EVIDENCE_RULE}

READ-ONLY: read files, list directories, and run read-only commands. Change NOTHING, install NOTHING, add no dependency, commit NOTHING — this recipe reports, a human decides.

Report every CANDIDATE: anything that plausibly covers some or all of what our capability does. Do NOT decide whether it really replaces ours — that is the next stage's job and it does it with both sources open. Report near-misses too: a candidate that turns out to do a different job costs one cheap comparison, while a candidate you never reported is invisible forever. Zero candidates is a valid, good result — an ecosystem that has not caught up is half of what this recipe is looking for.`

// The verifier is the entire reason this recipe is not a registry search. "A plugin named
// skill-creator exists" does not mean "our skill authoring is redundant" — the overlap that
// matters is of FUNCTION, and a naive version of this recipe reads the name match and tells
// you to delete something load-bearing. So the verifier gets both sides in full (ours: what
// it does and where its source is; theirs: the citation to open), is made to write down what
// each one actually does before it is allowed to judge, and is told which way to fail.
const verifyPrompt = (cap, c) => `Decide whether ONE ecosystem candidate actually covers ONE capability this project maintains. Compare what each one DOES.

OURS
  name: ${cap.name}
  what it does: ${cap.whatItDoes}
  where it lives: ${cap.whereItLives || '(not stated — find it in this repo before judging; never judge ours from its name)'}

THEIRS — as reported by the probe. Treat every line of it as a CLAIM to check, not as a fact.
  surface: ${c.surface}
  provider: ${c.provider}
  citation: ${c.citation}
  what the probe says it provides: ${c.whatItProvides}

Work in this order:
1) Confirm the citation is real — open the file, list the registry, run the read-only command. If you cannot confirm the cited artifact exists, coverage='none' and say the citation did not check out.
2) Establish what THEIRS does, from its own documentation or source.
3) Establish what OURS does, from ${cap.whereItLives || 'its implementation in this repo'} — not from its name and not from a README's marketing line.
4) Only then compare, behaviour by behaviour.

NAME OVERLAP IS NOT FUNCTION OVERLAP, and confusing the two is the failure this stage exists to prevent. Two things called the same noun routinely do different jobs: one authors an artifact interactively where ours validates and registers artifacts against a fixed layout; one covers the generic case where ours encodes rules that only hold in this project. The reverse happens too — two things with unrelated names can be exact substitutes. Neither the names nor the categories decide this. The behaviour decides it.

coverage='full' ONLY if adopting theirs means ours could be deleted with nothing of value lost: everything ours does for the people who use it, theirs does at least as well.
coverage='partial' if theirs does part of the job — then stillOurs must name PRECISELY what theirs does not do, because that remainder is the reason ours still exists.
coverage='none' if theirs shares a name, a topic or a category with ours but not the job.

When the comparison is ambiguous, coverage='none'. The two errors are not symmetric: a wrong 'full' tells a team to delete something load-bearing and they find out in production, while a wrong 'none' costs them some maintenance they could have dropped. Fail toward keeping.

stillOurs is required even when coverage='full' — say what would be lost by adopting theirs, or 'nothing' if genuinely nothing would be.
READ-ONLY: read, list, and run read-only commands. Change NOTHING, install NOTHING, commit NOTHING.`

const probed = await pipeline(
  A.capabilities,
  (cap) => agent(probePrompt(cap), { label: `probe:${String(cap.name).slice(0, 40)}`, phase: 'Probe', schema: CANDIDATES_SCHEMA }),
  (r, cap) => {
    // A probe that DIED returns no candidates — and "no candidates" is exactly what an
    // ecosystem that has not caught up looks like. Left as-is, the most dangerous
    // confusion this recipe can produce follows: a capability nobody checked comes back
    // reading DIFFERENTIATED, i.e. "keep building, nothing covers it", on the strength of
    // a search that never ran. So a dead probe becomes an explicit unknown-coverage entry
    // right here at the point of the call, and the classifier below turns any unknown into
    // UNVERIFIED. Recovering later is not possible: by then it is an empty array.
    if (!r || !Array.isArray(r.candidates)) {
      return {
        candidates: [
          {
            surface: '(none)',
            provider: '(unknown)',
            citation: '(none)',
            whatItProvides: '(the probe agent returned no report)',
            coverage: 'unknown',
            theirs: '(not established)',
            ours: '(not established)',
            stillOurs: '(unknown)',
            reason: 'probe agent returned no report — this capability was never checked against any surface',
          },
        ],
        checked: [],
        notCheckable: surfaces.map((s) => `${s.key} (probe agent returned no report)`),
      }
    }
    return parallel(
      r.candidates.map((c) => () =>
        agent(verifyPrompt(cap, c), {
          label: `verify:${String(cap.name).slice(0, 24)}:${String(c.provider || '?').slice(0, 24)}`,
          phase: 'Verify',
          effort: 'high',
          schema: COMPARISON_SCHEMA,
        }).then((d) => ({
          // Three states, never two. A verifier that DIED is not a verifier that found no
          // overlap: collapsing them into 'none' would exonerate the candidate and let the
          // capability read DIFFERENTIATED off a comparison nobody made. Same discipline as
          // `audit` and `consistency-sweep`: full | partial | none | unknown.
          ...c,
          coverage: d ? (d.coverage === 'full' ? 'full' : d.coverage === 'partial' ? 'partial' : 'none') : 'unknown',
          // An unrecognised coverage value falls to 'none' above — the direction that keeps
          // a capability alive. Being wrong there costs maintenance; being wrong the other
          // way deletes something load-bearing.
          theirs: (d && d.theirs) || '(not established — verifier returned no report)',
          ours: (d && d.ours) || '(not established — verifier returned no report)',
          stillOurs: (d && d.stillOurs) || '(unknown — verifier returned no report)',
          reason: (d && d.reason) || 'verifier agent returned no report',
        }))
      )
    ).then((verified) => ({
      candidates: verified,
      checked: Array.isArray(r.checkedSurfaces) ? r.checkedSurfaces : [],
      notCheckable: Array.isArray(r.notCheckable) ? r.notCheckable : [],
    }))
  }
)

// Index-aligned at BOTH layers, and the outer one is the easy mistake.
// `pipeline` preserves input order and yields null for a capability whose stage threw
// outright, so dropping the falsy entries here silently deletes an ENTIRE capability —
// and a capability missing from the report is a capability the reader assumes is fine.
// The inner recovery only ever sees nulls *within* a surviving capability's array, so it
// cannot cover this case no matter where it is placed.
const assessed = probed.map((r, i) => {
  const cap = A.capabilities[i]
  const candidates = (r && Array.isArray(r.candidates)
    ? r.candidates
    : [
        {
          surface: '(none)',
          provider: '(unknown)',
          citation: '(none)',
          whatItProvides: `(capability never checked: "${cap && cap.name}")`,
          coverage: 'unknown',
          theirs: '(not established)',
          ours: '(not established)',
          stillOurs: '(unknown)',
          reason: 'the probe/verify stage errored for this entire capability',
        },
      ]
  ).map(
    // A verify thunk that threw resolves to null inside a surviving capability's array.
    (c) =>
      c || {
        surface: '(unknown)',
        provider: '(unknown)',
        citation: '(none)',
        whatItProvides: '(candidate lost — verifier thunk errored)',
        coverage: 'unknown',
        theirs: '(not established)',
        ours: '(not established)',
        stillOurs: '(unknown)',
        reason: 'verifier agent errored',
      }
  )
  const unknown = candidates.filter((c) => c.coverage === 'unknown')
  const full = candidates.filter((c) => c.coverage === 'full')
  const partial = candidates.filter((c) => c.coverage === 'partial')
  // UNVERIFIED outranks every other classification, including SUBSUMED. A capability with
  // one lost comparison has not earned a complete judgement in either direction — least of
  // all "stop maintaining this", which is the irreversible one.
  const classification = unknown.length ? 'UNVERIFIED' : full.length ? 'SUBSUMED' : partial.length ? 'OVERLAPPING' : 'DIFFERENTIATED'
  // The differentiator is computed from the verifiers' own words rather than asked of a
  // summarizing agent: "keep building this, and here is what still makes it yours" is the
  // half of this report that gets acted on, and a summarizer that drops a line loses it.
  const differentiator =
    classification === 'UNVERIFIED'
      ? '(not established — this capability was not fully checked; do not read it as differentiated)'
      : classification === 'SUBSUMED'
        ? '(nothing claimed as still ours — confirm the migration path before deleting anything)'
        : partial.length
          ? partial.map((c) => `vs ${c.provider}: ${c.stillOurs}`).join(' | ')
          : `nothing on the checked surfaces does this job — ${candidates.length} candidate(s) examined and refuted on behaviour`
  return {
    capability: cap && cap.name,
    classification,
    differentiator,
    subsumedBy: full.map((c) => ({ provider: c.provider, surface: c.surface, citation: c.citation, lostByAdopting: c.stillOurs, reason: c.reason })),
    partialOverlap: partial.map((c) => ({ provider: c.provider, surface: c.surface, citation: c.citation, theyDo: c.theirs, stillOurs: c.stillOurs })),
    candidates,
    checkedSurfaces: (r && r.checked) || [],
    notCheckable: (r && r.notCheckable) || [],
  }
})

const unverified = assessed.filter((a) => a.classification === 'UNVERIFIED')
const stopMaintaining = assessed.filter((a) => a.classification === 'SUBSUMED')
// Both halves come back, and the second is not the leftovers. A recipe that only ever says
// "delete things" is ignored the first time it is wrong; "keep building this, and here is
// precisely what still makes it yours" is what makes the verdict usable either way.
const keepBuilding = assessed.filter((a) => a.classification === 'OVERLAPPING' || a.classification === 'DIFFERENTIATED')
// Shared recipe contract: every recipe returns `verdict`, and INCOMPLETE is reserved across
// all of them for "an agent died, so this is not a complete judgement". A capability whose
// probe or verifier died must never be readable as one that survived the check.
const verdict = unverified.length
  ? 'INCOMPLETE'
  : stopMaintaining.length
    ? 'SUBSUMED'
    : keepBuilding.some((a) => a.classification === 'OVERLAPPING')
      ? 'OVERLAPPING'
      : 'DIFFERENTIATED'
const unreachable = assessed.reduce((n, a) => n + a.notCheckable.length, 0)
log(
  `landscape-check: ${verdict} — ${stopMaintaining.length} subsumed (stop maintaining), ${keepBuilding.length} still ours${
    unverified.length ? `, ${unverified.length} UNVERIFIED (never checked — must NOT be read as differentiated)` : ''
  }${unreachable ? `, ${unreachable} surface check(s) unreachable` : ''}`
)
return {
  timestamp: A.timestamp || '',
  verdict,
  surfaces: surfaces.map((s) => s.key),
  stopMaintaining,
  keepBuilding,
  unverified,
  assessed,
}
