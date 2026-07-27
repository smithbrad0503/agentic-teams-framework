"""Structural tests for the `consistency-sweep` recipe.

The recipe cannot be executed by pytest — it runs against a live agent host — so
every property here is asserted against the source text. Each test names the
failure mode it is defending against.
"""

from pathlib import Path

RECIPES = Path(__file__).resolve().parents[1] / ".claude" / "workflows" / "recipes"
STEM = "consistency-sweep"
SOURCE = (RECIPES / f"{STEM}.js").read_text(encoding="utf-8")


def _between(start: str, end: str) -> str:
    """Slice the source between two anchors, failing loudly if either moved."""
    assert start in SOURCE, f"anchor not found: {start}"
    tail = SOURCE.split(start, 1)[1]
    assert end in tail, f"anchor not found after {start!r}: {end}"
    return tail.split(end, 1)[0]


META_BLOCK = _between("export const meta = {", "\n}\n")
SWEEP_PROMPT = _between("const sweepPrompt", "const verifyPrompt")
VERIFY_PROMPT = _between("const verifyPrompt", "const swept")
SURFACES_BLOCK = _between("const DEFAULT_SURFACES = [", "]\n")
RETURN_BLOCK = SOURCE.split("return {")[-1]


def test_meta_is_a_pure_literal_named_for_its_file() -> None:
    """The dispatcher reads `meta` without running the script.

    It is parsed statically, so anything computed — args, template
    interpolation, a require — makes the recipe undiscoverable. And `meta.name`
    is how a caller addresses the recipe: if it drifts from the filename stem,
    the recipe is listed under one name and invoked under another.
    """
    assert "export const meta" in SOURCE, "missing meta export"
    assert f"name: '{STEM}'" in SOURCE, "meta.name must equal the filename stem"
    assert "description:" in META_BLOCK and "phases:" in META_BLOCK
    for computed in ("${", "args", "require(", "process."):
        assert computed not in META_BLOCK, f"meta must be a pure literal, found {computed!r}"


def test_no_wall_clock_or_random_calls() -> None:
    """Workflow resume replays the script; non-deterministic calls diverge.

    A resumed run that re-reads the clock or the RNG produces different values
    than the run it is resuming, so the timestamp must arrive through args.
    """
    for banned in ("Date.now", "Math.random", "new Date("):
        assert banned not in SOURCE, f"{banned} breaks Workflow resume"
    assert "A.timestamp" in SOURCE, "the timestamp must come from args, not from the clock"


def test_args_are_normalized_and_validated_before_any_agent_spawns() -> None:
    """Bad args must fail as a returned error, not as a half-spent run.

    Args can arrive as a JSON string from the host, and a sweep with no
    contract has nothing to sweep against — discovering either after fanning
    out one agent per surface burns the whole budget to produce nothing.
    """
    assert "typeof A === 'string'" in SOURCE, "missing the string-args normalization guard"
    assert "JSON.parse(A)" in SOURCE, "string args must be parsed, not passed through"
    assert "unparseable string" in SOURCE, "an unparseable args string must return an error"

    guard = SOURCE.split("const VIOLATIONS_SCHEMA")[0]
    assert "if (!A.contractPath && !A.contract)" in guard, (
        "a sweep with neither contractPath nor contract must be rejected"
    )
    assert guard.count("return { error:") >= 2, "arg validation must return {error: ...}, not throw"
    assert "!s.key || !s.scope" in SOURCE, "surfaces entries must be validated for {key, scope}"

    # Validation has to run before the fan-out, not alongside it.
    assert SOURCE.index("if (!A.contractPath") < SOURCE.index("await pipeline"), (
        "the contract guard must precede the pipeline"
    )


def test_contract_may_be_a_pointer_to_a_repo_file() -> None:
    """An inlined contract is a second copy of the rules, and copies drift.

    Pointing agents at the live file means the sweep is always run against the
    contract as it is now, not as it was when someone pasted it into a call.
    """
    assert "A.contractPath" in SOURCE, "contractPath must be supported"
    assert "contractPath" in SOURCE.split("---- args contract")[1].split("let A =")[0], (
        "the args contract block must document contractPath"
    )
    contract_const = _between("const CONTRACT = ", "\n\nconst GREP_STEP")
    assert contract_const.startswith("A.contractPath"), (
        "contractPath must select a different prompt than an inlined contract"
    )
    assert "${A.contractPath}" in contract_const, "the pointer branch must name the file for the agent"
    assert "${A.contract}" in contract_const, "the inline branch must still be supported as a fallback"
    assert "source of truth" in contract_const, (
        "the prompt must tell the agent the file — not any quoted copy — is authoritative"
    )


def test_verification_is_context_sensitive_not_string_matching() -> None:
    """This is the property that separates the recipe from `grep`.

    The same token is a violation in shipped copy and entirely legitimate in a
    changelog, a migration guide, or a test fixture pinning the old wording. A
    verifier handed only the matched string can do nothing but re-confirm that
    the string exists — which the sweeper already reported. So the verifier
    prompt must carry the surface it was found on and the lines around it, and
    must be told to decide from those.
    """
    # The surface reaches the verifier at all: the pipeline's second stage takes it,
    # and the prompt builder is given it.
    assert "(r, s) =>" in SOURCE, "the verify stage must receive the surface, not just the sweep result"
    assert "verifyPrompt(v, s)" in SOURCE, "the verify prompt must be built from the violation AND the surface"

    # …and actually uses it, rather than accepting it and ignoring it.
    assert "${s.key}" in VERIFY_PROMPT, "the verifier must be told which surface the hit is on"
    assert "${s.scope}" in VERIFY_PROMPT, (
        "the surface key alone is a label; the verifier needs the scope to know what that "
        "surface means"
    )

    # The surrounding lines travel with the finding, sweeper -> verifier.
    assert "context: { type: 'string'" in SOURCE, "the sweep schema must collect surrounding context"
    assert "required: ['file', 'where', 'text', 'context', 'rule']" in SOURCE, (
        "context must be REQUIRED of the sweeper, not optional — an optional field is the "
        "one that never gets filled in"
    )
    assert "v.context" in VERIFY_PROMPT, "the verifier must receive the surrounding lines"

    interpolated = {f for f in ("v.file", "v.where", "v.text", "v.context", "v.rule") if f in VERIFY_PROMPT}
    assert len(interpolated) >= 5, (
        f"the verifier is being handed too little to judge context: only {sorted(interpolated)}"
    )

    lowered = VERIFY_PROMPT.lower()
    for legitimate_use in ("changelog", "decision log", "migration", "fixture"):
        assert legitimate_use in lowered, (
            f"the verifier must be told that a hit inside a {legitimate_use} is not a violation"
        )
    assert "ambiguous" in lowered, "an ambiguous context must resolve to holds=false, and say so"


def test_grep_is_the_cheap_first_pass_and_reading_follows() -> None:
    """Grep is high recall and near-free; reading catches what grep cannot.

    Running them in the other order pays for the expensive pass on hits the
    cheap one would have found, and dropping the read pass reduces the recipe
    to a literal-string matcher that misses paraphrase and implied claims.
    """
    assert "const GREP_STEP" in SOURCE, "the forbidden-term grep must be an explicit stage"
    assert "${GREP_STEP}" in SWEEP_PROMPT, "the grep step must be part of the sweep prompt"
    assert "A.forbidden" in SOURCE, "args.forbidden feeds the cheap pass"
    assert SWEEP_PROMPT.index("${GREP_STEP}") < SWEEP_PROMPT.index("THEN READ"), (
        "the cheap grep pass must come before the expensive read pass"
    )
    for subtle in ("paraphrase", "implied", "tone"):
        assert subtle in SWEEP_PROMPT.lower(), (
            f"the read pass must hunt {subtle} violations — grep already covers literals"
        )


def test_a_dead_verifier_surfaces_as_unverified_and_is_returned() -> None:
    """A crashed verifier must never read as a clean sweep.

    Mapping a null agent result onto the same falsy verdict as "not a
    violation" fails open: the finding is discarded and the run reports fewer
    problems than the repo has. Three states are required — confirmed,
    refuted, unverified — and the unverified list has to reach the caller,
    because a count in the log alone still drops it from the result.
    """
    assert "'unverified'" in SOURCE, "unverified must be a distinct verdict"
    assert "'confirmed'" in SOURCE and "'refuted'" in SOURCE, "all three verdicts must exist"
    assert "d ? (d.holds ? 'confirmed' : 'refuted') : 'unverified'" in SOURCE, (
        "a null verdict must map to unverified, never collapse into refuted"
    )
    assert "verdict: !!(" not in SOURCE and "confirmed: verdict ? !verdict.refuted : false" not in SOURCE, (
        "the collapsed truthiness check is the bug being defended against"
    )
    assert "thunk errored" in SOURCE, (
        "a verify thunk that threw resolves to null and must be recovered, not filtered away"
    )
    assert "unverified" in RETURN_BLOCK, "the unverified findings must be returned to the caller"
    assert "INCOMPLETE" in SOURCE, "a sweep with a dead verifier must not be able to report CLEAN"
    assert "unverified.length ? 'INCOMPLETE'" in SOURCE, (
        "the degraded verdict must be driven by the unverified count"
    )


def test_output_splits_public_facing_from_internal_hygiene() -> None:
    """The two lists have different urgency and must both come back.

    A violation in shipped copy blocks a public build; the same wording in an
    internal doc is cleanup. Collapsing them into one list makes the caller
    re-triage by hand, and returning only the urgent one hides the rot that
    re-infects the next thing written.
    """
    assert "fixBeforePublic" in RETURN_BLOCK, "the public-facing fix list must be returned"
    assert "internalHygiene" in RETURN_BLOCK, "the internal hygiene list must be returned"
    assert "exposure" in SOURCE, "the split is driven by a per-violation exposure judgement"
    assert "enum: ['public', 'internal']" in SOURCE, "the verifier must classify exposure"
    assert "d.exposure === 'internal' ? 'internal' : 'public'" in SOURCE, (
        "unrecognised exposure must fail toward public — the expensive direction"
    )
    assert "'unknown'" in SOURCE, "an unverified finding has no known exposure and must say so"


def test_every_stage_is_read_only() -> None:
    """The recipe reports; it never rewrites.

    An agent that "helpfully" fixes a violation it was asked to verify destroys
    the evidence for the finding and edits files the caller never approved — and
    a consistency rewrite touches user-visible copy, which is exactly the class
    of change a human signs off on.
    """
    assert "READ-ONLY" in SWEEP_PROMPT, "the sweeper must be told it is read-only"
    assert "READ-ONLY" in VERIFY_PROMPT, "the verifier must be told it is read-only"
    assert "Change NOTHING" in SWEEP_PROMPT, "the sweeper needs an explicit no-write instruction"
    assert "change NOTHING" in VERIFY_PROMPT, "the verifier needs an explicit no-write instruction"
    for mutation in ("git commit", "git push", "git checkout", "writeFile", "fs.write", "apply the fix"):
        assert mutation not in SOURCE, f"a read-only recipe must not {mutation!r}"


def test_default_surfaces_keep_the_outward_to_internal_ordering() -> None:
    """The surface list is a reusable checklist, and its order is the checklist.

    Outward-facing first means the tiers that block a public release are swept
    before the ones that are merely untidy, and a caller reading the defaults
    sees which tiers exist at all — a sweep that skips a tier does not know it
    skipped it.
    """
    import re

    keys = re.findall(r"key: '([^']+)'", SURFACES_BLOCK)
    assert keys == [
        "user-strings",
        "data-content",
        "code-literals",
        "internal-docs",
        "marketing",
    ], f"default surface ordering changed: {keys}"
    assert all("scope:" in line for line in SURFACES_BLOCK.strip().splitlines() if "key:" in line), (
        "every default surface needs a scope — a bare key tells an agent nothing"
    )
    assert "A.surfaces.length ? A.surfaces : DEFAULT_SURFACES" in SOURCE, (
        "callers may override the surfaces, but the default list must apply when they do not"
    )
