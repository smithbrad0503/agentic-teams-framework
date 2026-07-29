---
name: recipe-new
description: Author a new Workflow recipe script, plus its structural test, from the seven proven recipes in this library. Use when the user runs /recipe-new, asks to create or add a new recipe or workflow script, wants to automate a recurring multi-agent job (sweep, audit, gate, batch, triage), or asks how a recipe is structured and what its invariants are.
---

# /recipe-new — Author a Workflow Recipe

Write a new recipe by scaffolding from an existing one, not from scratch. Every
rule below was paid for by a defect in this repo. A recipe that violates one
does not fail loudly — it returns a result that looks fine and is not.

## 1. Prerequisites — where recipes live

| Location | What it is |
|---|---|
| `${CLAUDE_PLUGIN_ROOT}/.claude/workflows/recipes/` | The library. New recipes are authored HERE. |
| `<project>/.claude/workflows/` | Where `/org-init` copies a selected recipe (flattened out of `recipes/`, provenance header prepended as line 1). |
| `tests/test_recipes.py` | The parametrized invariant tests. Every recipe name must be in its `NAMES` list. |
| `tests/test_recipe_<name>.py` | The per-recipe structural test you will also write. |

```bash
# ${CLAUDE_PLUGIN_ROOT} is set when this skill runs from an INSTALLED plugin. Working
# in a checkout of the framework repo it is unset, and the line below would resolve to
# "/.claude/..." and error. Repo root and plugin root are the same tree, so:
ls "${CLAUDE_PLUGIN_ROOT:-.}/.claude/workflows/recipes/"
```

Read `.claude/workflows/team-run.js`'s header block first — it states the host
contract (`agent`, `parallel`, `pipeline`, `phase`, `log`, `budget`, `args`) that
every recipe is written against.

A recipe is invoked directly through the Workflow tool, never through `/team`:

```
Workflow({name: '<name>', args: {…, timestamp: '<ISO8601 now>'}})
```

## 2. Interview (one question at a time)

**If your brief already answers these, do not interrogate anyway.** Restate the answers
you were given, name any the brief left open, ask only about those, and continue.
Asking a question whose answer is already in front of you is pure stall.

Six questions. Do not skip any — each one selects a different part of the shape.

1. **The job** — what recurring job does this automate? One sentence, as the
   person asking would say it. This becomes `meta.description`.
2. **The args** — what does the caller pass in? Name every field, mark which are
   required, and note that `timestamp` is always among them (scripts cannot call
   `Date`).
3. **Fan-out** — does the work split into N independent items (checks, files,
   surfaces, targets, reported symptoms)? How does the caller supply that list?
4. **Writes** — does any stage create, edit, commit or delete a file? Which one,
   and exactly which files? Everything else is read-only.
5. **Exclusive resources** — does any stage need something that cannot be shared:
   a build lock, one device or emulator, a licence seat, a deploy slot, or a
   single shared file that several items all have to be written into?
6. **The verdict** — what are the possible answers this recipe returns? Name the
   good one, the bad one, and confirm that `INCOMPLETE` is reserved (see §4.5).

## 3. Pattern selection — scaffold from evidence

Map the answers onto the closest proven recipe and **read that file before
writing a line**. The point is to copy a shape that already survived production,
not to invent one.

| The answers look like… | Model recipe | Shape you are copying |
|---|---|---|
| N independent read-only checks, one verdict | `health-check.js` | `parallel()` over checks, `ran` separate from `ok` |
| N checks, then each finding challenged | `audit.js` | `pipeline()` sweep → nested `parallel()` verify, three-state verdict |
| Sweep several surfaces, context decides each finding | `consistency-sweep.js` | Same as audit, but the verifier gets the surrounding lines, never the matched string alone |
| Unstructured human input → dispatchable work | `triage.js` | Split → per-item diagnose → consolidate, with recovery at all three layers |
| N items that all write into the SAME file | `batch-author.js` | Parallel read-only authors, **one serialized writer**, index-aligned recovery |
| Some checks need an exclusive resource | `release-gate.js` | Serial `for await` chain as ONE element of a `parallel()` array |
| One agent writes one document | `retro.js` | Single `agent()`, INCOMPLETE and the error path are the same event |
| An **agent discovers** the list to fan out over | `first-run.js` | Discovery head (one agent maps the real journey) → `pipeline()` body over what it found |
| Per-item pass, then **one cross-cutting question** over all results | `dependency-probe.js` | `parallel()` as a genuine barrier — synthesis is unanswerable over a subset — then a synthesis agent whose death degrades the verdict |
| Two sources that must be compared **without contaminating each other** | `state-reconcile.js` | Blind double-gather: both prompts frozen as consts *above* the `parallel()`, so leaking one into the other is a `ReferenceError`, not a silent bias |

Two rules on top of the table:

- **`pipeline()` is the default.** It preserves input order and yields `null`
  where a stage thunk threw, which is what makes index-aligned recovery possible.
  Its signature is **not documented in `team-run.js`'s header** — read it off the
  recipes: `pipeline(items, stage1, stage2, …)`, where each stage callback receives
  `(previousResult, originalItem, index)`. Later stages need `originalItem`/`index`
  to label work without threading context through the first stage's return value.
- **`parallel()` only for a genuine barrier** — a stage that truly needs every
  prior result at once before it can start. Reach for it when the recipe's own
  shape requires the barrier, not because parallel sounds faster.
- If two rows both fit, the recipe probably wants two phases. Say so and design
  the phases explicitly rather than compressing them.

## 4. Generate the recipe

Write `${CLAUDE_PLUGIN_ROOT}/.claude/workflows/recipes/<name>.js`, in this order.

### 4.1 The `meta` literal — first thing in the file

```js
export const meta = {
  name: '<name>',
  description: '<one sentence — what the recipe decides, and whether it writes>',
  phases: [{ title: 'Check', detail: 'one read-only agent per configured check' }],
}
```

- **`meta` must be a pure literal.** No variables, no function calls, no template
  interpolation, no reads of `args`. The host parses `meta` **without running the
  script**, so anything computed there is invisible to the loader.
- **Required fields: `name` and `description`.** `phases` is optional but earns
  its keep on anything multi-stage — it is what makes a long run legible.
- **`meta.name` must equal the filename stem.** `foo.js` → `name: 'foo'`. A drift
  here makes the recipe undiscoverable by the name callers type. A test enforces it.

### 4.2 No wall clock, no randomness

**`Date.now()`, `Math.random()`, and argless `new Date()` are forbidden.** A
resumed Workflow replays the script; a wall-clock read or an RNG call makes the
replay diverge from the original run, and resume silently produces a different
answer. Timestamps arrive through `args.timestamp` and are echoed back in the
result. A test in `tests/test_recipes.py` enforces this for every recipe.

**The grep is over raw source, comments included.** Writing a comment that merely
*mentions* one of the banned tokens — even to explain why it is banned — fails the
test. Refer to them in prose instead ("a wall-clock read", "an RNG call"). The same
trap applies to any check that greps raw text: `.filter(Boolean)` in an explanatory
comment can trip a no-silent-drop assertion, and a comment quoting a slice anchor can
break a test that slices by that anchor. When writing your own tests (§5), take
anchors against comment-stripped source, not the raw file.

If you need a derived stamp (a filename, say), derive it from `A.timestamp`:

```js
const FILE = `docs/retros/retro-${A.timestamp.replace(/[-:]/g, '').slice(0, 13)}.md`
```

### 4.3 Args contract, normalization, validation

Every recipe opens with the same three blocks, in this order:

```js
// ---- args contract -------------------------------------------------------
// {
//   checks: [{ name: 'api-up', instructions: 'curl the /health endpoint …' }, …],
//   timestamp: '2026-01-01T10:30:00-05:00',   // dispatcher-generated (no Date in scripts)
// }
let A = args || {}
if (typeof A === 'string') {
  try {
    A = JSON.parse(A)
  } catch (e) {
    return { error: '<name>: args arrived as an unparseable string — pass a JSON object' }
  }
}
if (!Array.isArray(A.checks) || !A.checks.length) {
  return { error: '<name>: args.checks must be a non-empty array of {name, instructions}' }
}
```

Some hosts hand `args` over as a JSON string. Without the guard every `A.<field>`
read is `undefined` and the recipe fans out agents against an empty spec.

**Validate every required arg before the first `agent()` call.** Validation after
the first spawn is validation that already cost money and already told a subagent
to go do something. Return `{error: '…'}` — a structured error, never a throw.

### 4.4 Schemas and prompts

Declare a JSON schema per structured stage (`const CHECK_SCHEMA = {…}`) with
`required` naming every field the recipe actually reads. Give every `agent()` call
`{label, phase, schema}`; `effort: 'high'` for stages whose output everything
downstream depends on.

Safety in the prompt, in words:

- If the recipe is read-only, **say so in every agent prompt**: `READ-ONLY: read
  files and run read-only commands, change NOTHING and commit NOTHING.` A stage
  named "Audit" does not stop an agent from helpfully fixing what it found.
- If a stage writes, `meta.description` must say the recipe writes, and the
  writing prompt must name exactly what it may touch, state that it is the only
  writer, and forbid pushing to the default branch and opening or merging a PR.
- Never let two agents write the same file concurrently. Parallelize the
  thinking, serialize the writing — `batch-author.js` is the worked case.

### 4.5 The verdict, and what INCOMPLETE means

**Every recipe returns a `verdict` field, and `INCOMPLETE` is reserved across all
of them for "an agent died, so this is not a complete judgement."**

Why it is pinned this hard: six recipes independently invented four different
spellings of this idea before it was fixed, and three separate defects in this
repo trace back to the same under-modeled thought — an audit that silently
exonerated findings it could not check, a runner that reported a stale terminal
status, and an event stream that flattened four outcomes into one. `verdict` is
the one field a caller can read without knowing which recipe produced the result.

```js
const verdict = unrun.length ? 'INCOMPLETE' : failing.length ? 'UNHEALTHY' : 'HEALTHY'
return { timestamp: A.timestamp || '', verdict, results: settled, failing, unrun }
```

Rules:

- **INCOMPLETE outranks every other verdict.** A run that lost coverage is not
  entitled to a complete judgement, good or bad. Calling it `NO-SHIP` instead
  invites "fix that one failure and ship" — the path that must never open.
- Name the other verdicts for the domain: `HEALTHY`/`UNHEALTHY`, `CLEAN`/`FINDINGS`,
  `SHIP`/`NO-SHIP`, `TRIAGED`, `AUTHORED`/`REJECTED`, `WRITTEN`.
- Compute the verdict **in code**, never in an agent's output — then a dead
  reporting agent cannot turn an INCOMPLETE into something more comfortable.
- Return the degraded items too (`unrun`, `unverified`, `undiagnosed`, `failed`).
  A count in `log()` is not a report: the caller acts on the returned object.

### 4.6 A dead agent must never silently vanish

`agent()` returns null when the subagent produces no report, and `parallel()` /
`pipeline()` resolve a thunk that threw to null. **`.filter(Boolean)` over such an
array is precisely how work disappears without a trace** — the run comes back
green and shorter than it should be, and nothing anywhere says so.

Two legal recoveries, both used throughout the library:

```js
// 1. Recover by index — the result array is aligned with the input array.
const settled = results.map((r, i) => r || { name: A.checks[i].name, ran: false, detail: 'check agent errored' })

// 2. Map to an explicit failed/unverified entry at the point of the call.
.then((v) => ({ ...f, verdict: v ? (v.real ? 'confirmed' : 'refuted') : 'unverified' }))
```

Never a third state collapsed into a second one:

| Real event | Must not be reported as |
|---|---|
| verifier died | "refuted" (silently exonerates the finding — fails OPEN) |
| gate never ran | "fail" (a complete judgement it did not earn) |
| author died | an absent target (a batch of 7/10 that reads as success) |
| splitter died | an empty report (a clean bill of health for input nobody read) |

Where a recovery exists, put a comment above it saying *why*. A silent recovery
looks like defensive noise and gets deleted by the next reader.

## 5. Generate the structural test alongside it

The script **cannot be executed** by node or by pytest. It references host globals
(`agent`, `parallel`, `pipeline`, `phase`, `log`, `budget`, `args`), uses top-level
`await`, and returns at top level. There is nothing to import and nothing to run.
**Do not tell anyone to "just run it" — verification is structural.**

Write `tests/test_recipe_<name>.py`, modelled on `tests/test_recipe_batch_author.py`.

- Read the source once at module level; assert against the text.
- Strip whole-line `//` comments into a `CODE` string for anything that must hold
  in code rather than in prose — otherwise a comment mentioning `parallel(` passes
  a test that meant to forbid the call.
- Slice by anchors (`phase('Write')` → `phase('Verify')`) so a moved stage fails
  loudly instead of quietly widening the assertion.
- **Every test gets a docstring naming the failure mode it defends against.** The
  docstring is the durable half; the assertion alone teaches nobody why.

Then register the recipe so the shared parametrized invariants cover it:

```bash
# add "<name>" to the NAMES list
python3 - <<'PY'
import pathlib, re
p = pathlib.Path("tests/test_recipes.py")
print(re.search(r"NAMES = \[[^\]]*\]", p.read_text()).group(0))
PY
```

Registration is not optional: `NAMES` is what applies the meta-literal, stem-match,
no-wall-clock, verdict, and INCOMPLETE tests to your file.

**`NAMES` is not the only registry, and the other three are where users actually find
recipes.** A recipe absent from them exists but is invisible:

| Registry | Why it matters |
|---|---|
| `tests/test_recipes.py` `NAMES` | Applies the shared invariant tests. Without it your recipe is untested. |
| `README.md` (layout block) | The public list. |
| `skills/org-init/SKILL.md` (recipe catalog table) | **What `/org-init` offers a new project.** Unlisted means nobody is ever offered it. |
| `docs/ROADMAP.md` | Where shipped-vs-planned is tracked. |

Add a one-line description to the org-init catalog in the same voice as the existing rows.

### Mutation-check your own tests

A test whose assertion cannot fail is worse than no test — it is a green light
wired to nothing. Prove each one can fail before you believe it:

```bash
cp .claude/workflows/recipes/<name>.js /tmp/recipe-mutation.bak

# Break ONE invariant by hand, e.g. rename meta.name, delete the args guard,
# or replace an index-aligned recovery with .filter(Boolean).
python3 -m pytest -q tests/test_recipe_<name>.py   # MUST fail, on the test you expect

cp /tmp/recipe-mutation.bak .claude/workflows/recipes/<name>.js
python3 -m pytest -q tests/test_recipe_<name>.py   # green again
```

Do this at least for the single most important invariant in the recipe. If the
suite stays green while the invariant is broken, the test is asserting on the
wrong text — fix the test, not the recipe.

## 6. Verify, and say what you did not verify

```bash
python3 -m pytest -q
```

The whole suite must be green, including the parametrized tests now covering the
new name.

Then report honestly. What is verified: the structure of the file — the meta
literal, the stem match, the absence of wall-clock calls, the args guard, the
recovery shape, the verdict contract. **What is NOT verified: any runtime
behaviour.** No agent was spawned, no prompt was tried, no schema was exercised
against a real model, and the recipe has never run. Say that plainly rather than
letting a green suite imply it. The first real invocation is the first runtime
evidence — run it on something low-stakes.

## 7. Worked example — a complete, correct recipe

`link-check.js` — fan-out over N docs, read-only, index-aligned recovery.

```js
export const meta = {
  name: 'link-check',
  description: 'Check that every link target in a set of docs actually resolves. Read-only — reports breaks, never fixes them.',
  phases: [{ title: 'Check', detail: 'one read-only agent per doc' }],
}

// ---- args contract -------------------------------------------------------
// {
//   docs: ['README.md', 'docs/setup-guide.md'],   // required, non-empty
//   scope: 'repo-relative paths and in-page anchors',  // optional
//   timestamp: '2026-01-01T10:30:00-05:00',       // dispatcher-generated (no Date in scripts)
// }
let A = args || {}
if (typeof A === 'string') {
  try {
    A = JSON.parse(A)
  } catch (e) {
    return { error: 'link-check: args arrived as an unparseable string — pass a JSON object' }
  }
}
if (!Array.isArray(A.docs) || !A.docs.length) {
  return { error: 'link-check: args.docs must be a non-empty array of file paths' }
}

const SCOPE = A.scope || 'repo-relative paths and in-page anchors'
const LINKS_SCHEMA = {
  type: 'object',
  properties: {
    checked: { type: 'number', description: 'how many links were examined in this doc' },
    broken: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          link: { type: 'string', description: 'the link target, verbatim' },
          where: { type: 'string', description: 'line number or section heading' },
          why: { type: 'string', description: 'one line, ≤300 chars — what you checked and what was missing' },
        },
        required: ['link', 'where', 'why'],
      },
    },
  },
  required: ['checked', 'broken'],
}

phase('Check')
const results = await pipeline(A.docs, (doc) =>
  agent(
    `Check every link in ${doc}. In scope: ${SCOPE}.\n\n` +
      `READ-ONLY: read files and list directories to confirm each target resolves. Change NOTHING, fix NOTHING, commit NOTHING — this recipe reports, a human fixes.\n\n` +
      `For each link that does not resolve, give the target verbatim, where it sits, and one line on what you checked. Zero broken links is a valid, good result — do not invent breaks.`,
    { label: `check:${String(doc).slice(0, 40)}`, phase: 'Check', schema: LINKS_SCHEMA }
  ).then((r) =>
    r
      ? { doc, checked: r.checked || 0, broken: r.broken || [] }
      : { doc, unchecked: true, reason: 'checker agent returned no report' }
  )
)
// `pipeline` preserves doc order and yields null where a thunk threw. `.filter(Boolean)`
// here is exactly how a doc disappears from the report — a run that read 4 of 5 files
// and called them clean — so every index is mapped back to its doc instead.
const settled = results.map((r, i) => r || { doc: A.docs[i], unchecked: true, reason: 'checker agent errored before returning' })
const unchecked = settled.filter((r) => r.unchecked)
const broken = settled
  .filter((r) => !r.unchecked)
  .map((r) => r.broken.map((b) => ({ doc: r.doc, ...b })))
  .flat()
// Shared recipe contract: every recipe returns `verdict`, and INCOMPLETE is reserved
// across all of them for "an agent died, so this is not a complete judgement". A doc
// nobody read must never read as a doc with no broken links.
const verdict = unchecked.length ? 'INCOMPLETE' : broken.length ? 'BROKEN' : 'CLEAN'
log(`link-check: ${verdict} — ${broken.length} broken link(s) across ${settled.length - unchecked.length}/${A.docs.length} doc(s)${unchecked.length ? `, ${unchecked.length} NEVER CHECKED` : ''}`)
return { timestamp: A.timestamp || '', verdict, docs: A.docs, broken, unchecked }
```

And the head of its test — same file, one test per failure mode:

```python
"""link-check recipe: read-only fan-out, no doc silently dropped.

Structural tests on the source text. The recipe is a Workflow script — it cannot
be imported or executed by node or pytest — so the properties that keep it
correct are pinned against the file itself.
"""

from pathlib import Path

RECIPE = Path(__file__).resolve().parents[1] / ".claude" / "workflows" / "recipes" / "link-check.js"
SRC = RECIPE.read_text(encoding="utf-8")
CODE = "\n".join(l for l in SRC.splitlines() if not l.lstrip().startswith("//"))


def test_no_doc_is_silently_dropped() -> None:
    """A dead checker agent must not read as a doc with no broken links.

    `pipeline` yields null for a thrown thunk; filtering those out returns a
    shorter, cleaner-looking report than the repo deserves, with nothing saying so.
    """
    assert "filter(Boolean)" not in CODE, "recover by index, never filter"
    assert "A.docs.map((r, i)" in CODE or "results.map((r, i)" in CODE
    assert "unchecked: true" in CODE, "a lost doc must become an explicit unchecked entry"
    assert "'INCOMPLETE'" in CODE, "lost coverage must not yield CLEAN"
```

## 8. Hand over

Report: the recipe path, the test path, the `NAMES` registration, the pattern it
was scaffolded from, the mutation you used to prove the tests bite, the pytest
count — and the one-line invocation:

```
Workflow({name: '<name>', args: {…, timestamp: '<ISO8601 now>'}})
```

Offer to commit on a feature branch. Never push to the default branch.
