"""landscape-check recipe: function-overlap verification, and no capability checked-in-name-only.

The recipe answers "has the ecosystem started giving away something we still maintain?", so
its two dangerous failures are both quiet ones. It can tell a team to delete something
load-bearing because a plugin happens to share its name, and it can report a capability as
still differentiated when the probe that was supposed to check it died. Both come back
looking like a clean, confident answer. Every test below pins one of those.

These are structural tests on the source text. The recipe is a Workflow script — it
references host globals (`agent`, `parallel`, `pipeline`, `log`, `args`), uses top-level
`await` and returns at top level — so node and pytest both reject it on sight and there is
nothing to import or execute.

NOT covered here, and worth saying plainly: no runtime behaviour at all. No agent has been
spawned, no prompt tried, no schema exercised against a real model. A green run of this file
says the file is shaped correctly, never that the recipe works.
"""

import re
from pathlib import Path

RECIPE = Path(__file__).resolve().parents[1] / ".claude" / "workflows" / "recipes" / "landscape-check.js"
SRC = RECIPE.read_text(encoding="utf-8")


def _code_only(text: str) -> str:
    """Drop whole-line `//` comments.

    Invariants that must hold in code are asserted against this. The recipe's comments
    name several antipatterns in order to forbid them, so a whole-file substring check
    would happily pass on the prose that bans the thing it is looking for.
    """
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("//"))


CODE = _code_only(SRC)
# Whitespace-collapsed, so an assertion about an expression survives a reflow that wraps it
# across lines instead of failing on a formatting change nobody meant to make.
FLAT = " ".join(CODE.split())


def _between(text: str, start: str, end: str) -> str:
    """Slice between two anchors, failing loudly if either one moved or multiplied."""
    assert text.count(start) == 1, f"expected exactly one {start!r} anchor"
    tail = text.split(start, 1)[1]
    assert end in tail, f"anchor not found after {start!r}: {end!r}"
    return tail.split(end, 1)[0]


META_BLOCK = _between(SRC, "export const meta = {", "\n}\n")
PROBE_PROMPT = _between(CODE, "const probePrompt = (cap) =>", "const verifyPrompt")
VERIFY_PROMPT = _between(CODE, "const verifyPrompt = (cap, c) =>", "const probed = await pipeline")
SURFACES_BLOCK = _between(CODE, "const DEFAULT_SURFACES = [", "\n]\n")
COMPARISON_SCHEMA = _between(CODE, "const COMPARISON_SCHEMA = {", "\nconst EVIDENCE_RULE")
STAGE_TWO = _between(CODE, "(r, cap) => {", "const assessed")
RETURN_BLOCK = CODE.split("return {")[-1]


def test_meta_is_a_pure_literal_named_for_its_file() -> None:
    """The host parses `meta` without running the script.

    Anything interpolated, computed or read from args inside the literal is invisible to
    the loader, so the recipe advertises itself as something other than what it is. And
    `meta.name` is how a caller addresses it: drift from the filename stem and the recipe
    is listed under one name and invoked under another.
    """
    assert SRC.startswith("export const meta = {"), "meta must be the first thing in the file"
    assert "name: 'landscape-check'" in SRC, "meta.name must equal the filename stem"
    for computed in ("${", "args", "require(", "process."):
        assert computed not in META_BLOCK, f"meta must be a pure literal, found {computed!r}"
    for title in ("Probe", "Verify"):
        assert f"title: '{title}'" in META_BLOCK, f"meta.phases must declare the {title} phase"
    assert "Read-only" in META_BLOCK, "meta.description must tell a caller the recipe writes nothing"


def test_no_wall_clock_or_randomness() -> None:
    """Workflow resume replays the script; a clock read or an RNG call makes it diverge.

    The resumed run then produces a different answer than the one it is resuming, and
    nothing reports the difference. The timestamp has to arrive through args instead.
    """
    for banned in ("Date.now", "Math.random", "new Date("):
        assert banned not in SRC, f"{banned} breaks Workflow resume — and the grep is over raw source"
    assert "A.timestamp" in CODE, "the timestamp must come from args, not from the clock"


def test_args_are_normalized_and_validated_before_any_agent_spawns() -> None:
    """Bad args must fail as a returned error, not as a half-spent run.

    Some hosts hand args over as a JSON string; without the guard every `A.<field>` read is
    undefined and the recipe fans out one probe per capability against an empty list.
    Validating after the first spawn is validation that already cost money and already told
    a subagent to go do something.
    """
    assert "let A = args || {}" in CODE, "missing the args normalization guard"
    assert "typeof A === 'string'" in CODE, "the JSON-string case must be handled"
    assert "JSON.parse(A)" in CODE, "string args must be parsed, not passed through"
    assert "unparseable string" in CODE, "an unparseable args string must return an error"

    guard = CODE.split("const CANDIDATES_SCHEMA")[0]
    assert "!Array.isArray(A.capabilities) || !A.capabilities.length" in guard, (
        "an empty capabilities list has nothing to check and must be rejected"
    )
    assert "!s.key || !s.howToCheck" in guard, "surfaces entries must be validated for {key, howToCheck}"
    assert guard.count("return { error:") >= 3, "arg validation must return {error: ...}, never throw"
    assert CODE.index("!Array.isArray(A.capabilities)") < CODE.index("await pipeline"), (
        "validation must precede the fan-out, not run alongside it"
    )


def test_a_capability_must_arrive_with_its_function_not_just_a_name() -> None:
    """A bare name is what makes this recipe compare names.

    `{name: 'skill authoring'}` gives a verifier nothing to compare except the string, which
    is the exact confusion the Verify stage exists to prevent. What ours DOES is mandatory,
    and where its source lives is carried through so the verifier can read it rather than
    trusting the summary it was handed.
    """
    guard = CODE.split("const CANDIDATES_SCHEMA")[0]
    assert "!c.name || !c.whatItDoes" in guard, "a capability without whatItDoes must be rejected"
    assert "compare names instead of functions" in guard, (
        "the error must say WHY a bare name is rejected — otherwise the next reader relaxes it"
    )
    assert "${cap.whatItDoes}" in PROBE_PROMPT, "the probe must know what ours does, not just its name"
    assert "${cap.whatItDoes}" in VERIFY_PROMPT, "the verifier must know what ours does, not just its name"
    assert "cap.whereItLives" in VERIFY_PROMPT, (
        "the verifier must be pointed at our source so it can establish ours first-hand"
    )


def test_probe_demands_a_concrete_citation_and_refuses_recollection() -> None:
    """A model's memory of an ecosystem is stale exactly where this recipe is useful.

    "I believe there is a plugin for that" produces a candidate that a verifier then spends
    real budget refuting, or worse, half-confirms. The whole recipe exists because the
    ecosystem moved after everything was written about it, so a candidate has to point at
    something looked at in this run — and an unreachable surface has to be declared rather
    than imagined.
    """
    assert "const EVIDENCE_RULE" in CODE, "the evidence rule must be an explicit, reusable block"
    assert "${EVIDENCE_RULE}" in PROBE_PROMPT, "the evidence rule must reach the probe prompt"
    rule = _between(CODE, "const EVIDENCE_RULE = `", "`\n")
    lowered = rule.lower()
    assert "i believe" in lowered, "the recipe must name the exact phrasing it is refusing"
    assert "stale by construction" in lowered, "the probe must be told why its prior knowledge does not count"
    assert "report nothing rather than" in lowered, "silence must be preferred to a guess"
    assert "notcheckable" in lowered, "a surface that could not be checked must be declared, not guessed at"
    assert "required: ['surface', 'provider', 'citation', 'whatItProvides']" in CODE, (
        "citation must be REQUIRED of the probe — an optional evidence field is the one never filled in"
    )
    assert "Zero candidates is a valid, good result" in PROBE_PROMPT, (
        "a probe under pressure to find something invents something"
    )


def test_verification_compares_function_not_name() -> None:
    """"A plugin named skill-creator exists" is not "our skill authoring is redundant".

    This is the load-bearing stage. Two things called the same noun routinely do different
    jobs, and a naive version of this recipe reads the name match and recommends deleting
    something load-bearing. So the verifier is handed BOTH sides in full, is made to write
    down what each one actually does before it may answer, and is told which way to fail
    when the comparison is ambiguous — toward keeping, because the two errors are not
    symmetric.
    """
    assert "verifyPrompt(cap, c)" in CODE, (
        "the verify prompt must be built from our capability AND the candidate — a verifier "
        "given only the candidate can do nothing but confirm the candidate exists"
    )
    for ours in ("${cap.name}", "${cap.whatItDoes}"):
        assert ours in VERIFY_PROMPT, f"the verifier must be told {ours} about ours"
    for theirs in ("${c.provider}", "${c.citation}", "${c.whatItProvides}", "${c.surface}"):
        assert theirs in VERIFY_PROMPT, f"the verifier must be told {theirs} about theirs"

    assert "NAME OVERLAP IS NOT FUNCTION OVERLAP" in VERIFY_PROMPT, (
        "the rule must be stated to the verifier in words, not merely implied by the schema"
    )
    lowered = VERIFY_PROMPT.lower()
    assert "not from its name" in lowered, "both sides must be established from behaviour, not naming"
    assert "confirm the citation is real" in lowered, "an unconfirmable citation is not evidence of coverage"
    assert "ambiguous" in lowered and "fail toward keeping" in lowered, (
        "an ambiguous comparison must resolve toward keeping — a wrong 'full' deletes something "
        "load-bearing, a wrong 'none' costs some maintenance"
    )

    # The schema is the other half of the defence: `theirs` and `ours` are required and are
    # asked for BEFORE `coverage`, so the verdict cannot be produced from the two names.
    assert "required: ['theirs', 'ours', 'coverage', 'stillOurs', 'reason']" in COMPARISON_SCHEMA, (
        "the side-by-side must be required output, not optional commentary"
    )
    assert COMPARISON_SCHEMA.index("theirs:") < COMPARISON_SCHEMA.index("coverage:"), (
        "what each side does must be written down before the judgement is"
    )
    assert "enum: ['full', 'partial', 'none']" in COMPARISON_SCHEMA, "coverage must be a closed enum"
    assert "effort: 'high'" in CODE, "the load-bearing comparison must not be run cheaply"

    # An unrecognised coverage value falls to 'none' — the direction that keeps a capability.
    assert "d.coverage === 'full' ? 'full' : d.coverage === 'partial' ? 'partial' : 'none'" in FLAT, (
        "coverage must be normalized against the enum, and anything unrecognised must fail "
        "toward keeping rather than toward deleting"
    )


def test_a_dead_probe_can_never_read_as_differentiated() -> None:
    """The most dangerous failure this recipe has: reporting "still ours" without looking.

    A probe that died returns no candidates, and no candidates is exactly what an ecosystem
    that has not caught up looks like. Left alone, a capability nobody checked comes back
    classified DIFFERENTIATED — a confident "keep building this" off a search that never
    ran. The dead probe therefore becomes an explicit unknown-coverage entry at the point of
    the call, before any comparison happens, and unknown outranks every other state.
    """
    assert "if (!r || !Array.isArray(r.candidates))" in CODE, (
        "a probe that returned no report must be detected in the verify stage"
    )
    dead_branch = _between(STAGE_TWO, "if (!r || !Array.isArray(r.candidates))", "return parallel(")
    assert "coverage: 'unknown'" in dead_branch, (
        "a dead probe must produce an explicit unknown-coverage entry, not an empty candidate list"
    )
    assert "never checked against any surface" in dead_branch, (
        "the entry must say what actually happened — a reader acts on the returned object"
    )
    assert STAGE_TWO.index("if (!r ||") < STAGE_TWO.index("return parallel("), (
        "the dead-probe recovery must happen before the fan-out, not after: by then it is an "
        "empty array and indistinguishable from a clean result"
    )
    assert "const classification = unknown.length ? 'UNVERIFIED' : full.length ? 'SUBSUMED' : partial.length ? 'OVERLAPPING' : 'DIFFERENTIATED'" in FLAT, (
        "UNVERIFIED must outrank every other classification, and DIFFERENTIATED must be the "
        "last resort rather than the default for an empty result"
    )


def test_no_capability_is_silently_dropped_at_either_layer() -> None:
    """A capability missing from the report is a capability the reader assumes is fine.

    `pipeline` yields null for a capability whose stage threw outright, and `parallel`
    yields null for a verify thunk that threw. Filtering the falsy entries away deletes an
    entire capability at the outer layer and a single comparison at the inner one — the run
    comes back shorter, cleaner and wrong, with nothing anywhere saying so. Both layers
    recover by index instead.
    """
    assert "filter(Boolean)" not in CODE, "recover by index; never filter the dead away"
    assert "probed.map((r, i)" in CODE, "the outer layer must recover by index"
    assert "A.capabilities[i]" in CODE, "the outer recovery must map each null back to its capability"
    assert "capability never checked" in CODE, "a lost capability must become an explicit entry"
    assert "the probe/verify stage errored for this entire capability" in CODE, (
        "the outer failure must be distinguishable from the inner one when a human triages it"
    )
    assert "candidate lost — verifier thunk errored" in CODE, (
        "a verify thunk that threw resolves to null inside a surviving capability's array"
    )
    assert "verdict" in RETURN_BLOCK and "unverified" in RETURN_BLOCK, (
        "the degraded capabilities must reach the caller — a count in log() alone still drops them"
    )


def test_a_dead_verifier_is_not_a_verifier_that_found_no_overlap() -> None:
    """Collapsing a null comparison into 'none' exonerates the candidate and hides the loss.

    'none' means "checked, and theirs does a different job" — a real, useful result that
    leaves the capability reading DIFFERENTIATED. A verifier that died has established
    nothing. Four states are required, and the recipe must return the ones it could not
    establish.
    """
    assert "'unknown'" in CODE, "unknown must be a state distinct from 'none'"
    assert ": 'none') : 'unknown'" in FLAT, (
        "a null verifier result must map to unknown, never collapse into 'none'"
    )
    assert "verifier agent returned no report" in CODE, "the unknown entry must carry its reason"
    assert "const verdict = unverified.length ? 'INCOMPLETE'" in FLAT, (
        "INCOMPLETE is reserved for agent death and must outrank the domain verdicts"
    )
    for domain in ("'SUBSUMED'", "'OVERLAPPING'", "'DIFFERENTIATED'", "'UNVERIFIED'"):
        assert domain in CODE, f"the classification {domain} must exist"


def test_output_separates_stop_maintaining_from_keep_building() -> None:
    """A recipe that only ever says "delete things" is ignored the first time it is wrong.

    "Keep building this, and here is precisely what still makes it yours" is the half that
    gets acted on when the answer is not a deletion, and for a partial overlap it is the
    only actionable content there is. Both lists must come back, and the differentiator has
    to be computed in code from the verifiers' own words — a summarizing agent that drops a
    line loses exactly the sentence the reader needed.
    """
    assert "stopMaintaining" in RETURN_BLOCK, "the stop-maintaining list must be returned"
    assert "keepBuilding" in RETURN_BLOCK, "the keep-building list must be returned"
    assert "const keepBuilding = assessed.filter((a) => a.classification === 'OVERLAPPING' || a.classification === 'DIFFERENTIATED')" in FLAT, (
        "a partial overlap is still something we are building, and must not be filed under deletion"
    )
    assert "differentiator" in CODE, "every assessed capability must carry what is still ours"
    assert "stillOurs" in COMPARISON_SCHEMA, "the remainder must be required output of each comparison"
    assert "must name PRECISELY what theirs does not do" in VERIFY_PROMPT, (
        "a vague remainder is unusable — 'some things' is not a differentiation claim"
    )
    assert "subsumedBy" in CODE and "partialOverlap" in CODE, (
        "a SUBSUMED capability must name what to adopt instead, with the citation to check"
    )
    assert "lostByAdopting" in CODE, (
        "even a full subsumption has a migration cost, and the caller decides with it in hand"
    )


def test_every_stage_is_read_only() -> None:
    """This recipe reports; a human decides what to stop maintaining.

    The specific hazard here is not an over-helpful edit but an over-helpful adoption: an
    agent comparing our capability against a plugin is one step away from installing the
    plugin to try it. Read-only is a property of the prompt, in words, or it is not a
    property at all.
    """
    for name, prompt in (("probe", PROBE_PROMPT), ("verifier", VERIFY_PROMPT)):
        assert "READ-ONLY" in prompt, f"the {name} must be told it is read-only"
        assert "Change NOTHING" in prompt, f"the {name} needs an explicit no-write instruction"
        assert "install NOTHING" in prompt, (
            f"the {name} is one step from installing the thing it is evaluating"
        )
    for mutation in ("git commit", "git push", "git checkout", "writeFile", "fs.write", "npm install"):
        assert mutation not in SRC, f"a read-only recipe must not {mutation!r}"


def test_default_surfaces_keep_the_platform_first_ordering() -> None:
    """The surface list is a reusable checklist, and its order is the checklist.

    Coverage by a native platform feature is the strongest kind — nothing to install, no
    dependency to carry — while the same coverage from a community package means trading
    maintenance for an adoption risk. Reading them in that order means the decisive answer
    is found first, and a caller reading the defaults sees which tiers exist at all.
    """
    keys = re.findall(r"key: '([^']+)'", SURFACES_BLOCK)
    assert keys == [
        "platform-native",
        "official-extensions",
        "official-docs",
        "community-ecosystem",
    ], f"default surface ordering changed: {keys}"
    assert SURFACES_BLOCK.count("howToCheck") == len(keys), (
        "every default surface needs a howToCheck — a bare key tells a probe nothing"
    )
    assert "A.surfaces.length ? A.surfaces : DEFAULT_SURFACES" in CODE, (
        "callers may override the surfaces, but the defaults must apply when they do not"
    )
    assert "${surfaceList}" in PROBE_PROMPT, "the probe must actually be given the surfaces to check"
