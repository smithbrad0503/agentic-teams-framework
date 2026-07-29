"""dependency-probe recipe: read-only fan-out over third-party dependencies, a barrier
synthesis over the complete result set, and no lost coverage anywhere.

These are structural tests on the source text. The recipe is a Workflow script — it
references host globals (`agent`, `parallel`, `phase`, `log`, `args`), uses top-level
`await` and returns at top level, so it cannot be imported or executed by node or by
pytest. The properties that keep it honest are therefore pinned against the file itself,
where an edit that breaks one fails here rather than in production against a real provider.

Not covered here, and worth saying plainly: no runtime behaviour whatsoever. No agent has
been spawned, no prompt tried, no schema exercised against a model.
"""

from pathlib import Path

import pytest

RECIPE = Path(__file__).resolve().parents[1] / ".claude" / "workflows" / "recipes" / "dependency-probe.js"
SRC = RECIPE.read_text(encoding="utf-8")


def _code_only(text: str) -> str:
    """Drop whole-line `//` comments: invariants must hold in code, not in prose.

    Otherwise a comment mentioning `pipeline(` satisfies a test that meant to forbid the call.
    """
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("//"))


CODE = _code_only(SRC)


def _segment(text: str, start: str, end: str | None = None) -> str:
    assert text.count(start) == 1, f"expected exactly one {start!r} marker"
    tail = text.split(start, 1)[1]
    if end is None:
        return tail
    assert text.count(end) == 1, f"expected exactly one {end!r} marker"
    return tail.split(end, 1)[0]


def test_meta_is_a_pure_literal_named_for_the_file() -> None:
    """The host parses `meta` without running the script.

    Anything interpolated or computed in the literal is invisible to the loader, and a
    `meta.name` that drifts from the filename stem makes the recipe undiscoverable by the
    name callers actually type into Workflow({name: …}).
    """
    assert SRC.startswith("export const meta = {"), "meta must be the first thing in the file"
    assert "name: 'dependency-probe'" in SRC, "meta.name must equal the filename stem"
    block = SRC.split("export const meta = {", 1)[1].split("\n}\n", 1)[0]
    assert "${" not in block, "meta must be a pure literal — no interpolation"
    assert "args" not in block, "meta must be a pure literal — it cannot read args"
    for title in ("Probe", "Synthesize"):
        assert f"title: '{title}'" in block, f"meta.phases must declare the {title} phase"
    assert "Read-only" in block, "meta.description must state that the recipe writes nothing"


def test_no_wall_clock_or_randomness() -> None:
    """Non-determinism breaks Workflow resume.

    A resumed run replays the script; a wall-clock read or an RNG call makes the replay
    diverge from the original and the resume silently returns a different answer. The
    timestamp therefore arrives through args and is echoed back.
    """
    for banned in ("Date.now", "Math.random", "new Date("):
        assert banned not in SRC, f"{banned} breaks Workflow resume"
    assert "A.timestamp" in CODE, "the recipe must take its timestamp from args"


def test_args_normalize_from_a_json_string() -> None:
    """Some hosts hand `args` over as a JSON string rather than an object.

    Without the normalization guard every `A.<field>` read is undefined, the defaults
    silently take over, and the recipe fans out probers at a target nobody asked for.
    """
    assert "let A = args || {}" in CODE
    assert "typeof A === 'string'" in CODE
    assert "JSON.parse(A)" in CODE
    assert "return { error: 'dependency-probe: args arrived as an unparseable string" in CODE, (
        "unparseable args must return a structured error, not throw"
    )
    assert "Array.isArray(A)" in CODE, "an array is not a valid args object and must be rejected"


def test_required_args_are_validated_before_any_agent_spawns() -> None:
    """Validation after the first spawn already cost money and already dispatched a subagent.

    `target` is load-bearing: it is interpolated into every prompt, so an empty one sends
    N probers off to audit nothing in particular. The two optional list args are shape-checked
    in the same block, because a caller that passes `dependencies: []` means something
    different from a caller that omits it, and only one of those should get the defaults.
    """
    head = CODE.split("agent(", 1)[0]
    for field in ("A.target", "A.dependencies", "A.failureModes"):
        assert field in head, f"{field} must be checked before the first agent call"
    assert "return { error: 'dependency-probe: args.target is required" in head
    assert "Array.isArray(A.dependencies)" in head, "a supplied dependencies list must be checked for shape"
    assert "Array.isArray(A.failureModes)" in head, "a supplied failureModes list must be checked for shape"
    assert "args.only matched no dependency" in head, (
        "a subset filter that selects nothing must error, not silently probe zero dependencies"
    )


def test_both_lists_have_defaults_so_the_recipe_travels() -> None:
    """The recipe it derives from hardcoded 13 named integrations for one codebase.

    Dependencies and failure modes both come from args here; the defaults exist so the
    recipe is usable on a codebase whose third-party edges nobody has catalogued yet.
    """
    assert "const MODES = A.failureModes || DEFAULT_FAILURE_MODES" in CODE
    assert "const CATALOG = A.dependencies || DEFAULT_DEPENDENCIES" in CODE
    modes = _segment(CODE, "const DEFAULT_FAILURE_MODES = [", "const DEFAULT_DEPENDENCIES = [")
    for mode in (
        "provider-down",
        "rate-limited",
        "malformed-200",
        "timeout-mid-write",
        "schema-drift",
        "credential-expiry",
        "duplicate-delivery",
        "out-of-order-delivery",
    ):
        assert f"name: '{mode}'" in modes, f"the default failure modes must include {mode}"


def test_the_only_fan_out_is_the_probe_barrier() -> None:
    """`pipeline()` is the library default; `parallel()` is for a genuine barrier only.

    pipeline earns its place when each item has per-item downstream work that can start as
    soon as that item lands (audit verifies each finding as it arrives). This recipe has no
    per-item second stage — the only thing after Probe is Synthesize, which cannot start
    until every probe has resolved because its question is unanswerable over a subset. That
    is the barrier. If a future edit adds a per-item stage, this test should fail and the
    fan-out should become a pipeline again.
    """
    assert CODE.count("parallel(") == 1, "exactly one fan-out: the probe barrier"
    assert "pipeline(" not in CODE, "there is no per-item downstream stage to stage with pipeline()"
    assert CODE.index("await parallel(") < CODE.index("phase('Synthesize')"), (
        "the barrier must resolve before the synthesis stage begins"
    )


def test_the_barrier_is_justified_in_a_comment() -> None:
    """A parallel() in a library whose default is pipeline() looks like a mistake.

    Without the reason written down, the next reader either "fixes" it back to pipeline or
    copies parallel() into a recipe that has no barrier at all. The comment is the durable
    half of the choice, so it is pinned.
    """
    comments = "\n".join(line for line in SRC.splitlines() if line.lstrip().startswith("//")).lower()
    assert "pipeline" in comments, "the comment must say what the default is and why this differs"
    assert "barrier" in comments, "the comment must name the barrier that justifies parallel()"
    assert "subset" in comments or "every probe" in comments, (
        "the comment must state WHY synthesis needs the complete set"
    )


def test_no_dependency_is_silently_dropped() -> None:
    """A dead prober must never read as a dependency with no exposures.

    `parallel()` resolves a thunk that threw to null, and `agent()` returns null when the
    subagent files no report. `.filter(Boolean)` over those results is exactly how a
    dependency vanishes: the run comes back green and one item shorter than it should be,
    with nothing anywhere saying so. This is the bug in the recipe this one derives from,
    which filters dead agents out and then prints a clean summary.
    """
    assert "filter(Boolean)" not in CODE, (
        "filter(Boolean) over the probe results is precisely how a dependency disappears — "
        "recover by index instead"
    )
    assert "probes.map((r, i)" in CODE, "results must be reconciled against DEPS by index"
    assert "reconcile(DEPS[i], null)" in CODE, (
        "a lost probe must become an explicit not-ran entry for its own dependency"
    )
    assert "ran: !!r" in CODE, "each dependency must record whether its prober reported at all"
    assert "const unprobed = settled.filter((r) => !r.ran)" in CODE


def test_an_unreported_failure_mode_is_unchecked_not_handled() -> None:
    """"Nobody looked" must not be recorded as "we looked and it is covered".

    A prober that skips a mode, or returns a status string outside the enum, would otherwise
    default into the reassuring bucket — the same fail-open shape as a dead verifier
    exonerating a finding. Every configured mode is reconciled by name against what came
    back, and anything unrecognized lands on 'unchecked'.
    """
    assert "MODE_NAMES.map((name)" in CODE, "every configured mode must be reconciled by name"
    assert "STATUSES.includes(hit.status)" in CODE, "an unrecognized status must not be trusted"
    assert "status: 'unchecked'" in CODE, "an unreported mode must get its own explicit status"
    assert "'handled', 'exposed', 'not-applicable'" in CODE, "unchecked is deliberately not a reportable status"
    reconcile = _segment(CODE, "const reconcile = (dep, r) => {", "phase('Probe')")
    assert "'unchecked'" in reconcile and "hit.status" in reconcile
    assert "never reported on this failure mode" in reconcile, "the unchecked entry must say why it is unchecked"


def test_a_dead_synthesizer_degrades_the_verdict() -> None:
    """Shared-fate synthesis is the reason this recipe exists rather than another audit.

    Per-dependency probing cannot see one HTTP client with no timeout, one non-idempotent
    retry helper, or one credential used by six services — each dependency looks acceptable
    and they fall over together. A run that lost that stage and still returned RESILIENT
    would claim exactly the judgement it failed to make, on the strength of the stage that
    did not run. It must read as INCOMPLETE.
    """
    assert "!synthesis ? 'INCOMPLETE'" in CODE, "a dead synthesis agent must force INCOMPLETE"
    assert "synthesisRan: !!synthesis" in CODE, "the caller must be able to see that the stage ran"
    assert "synthesis.sharedFate : null" in CODE, (
        "an empty sharedFate list means 'looked, found nothing shared' — a real and reassuring "
        "result. A dead synthesizer must return null instead, never that good news"
    )
    synth = _segment(CODE, "phase('Synthesize')", "const verdict =")
    assert synth.count("agent(") == 1, "the synthesis stage is exactly one agent over the complete set"
    assert "JSON.stringify(digest" in synth, "the synthesizer must receive every dependency's result"
    assert "NEVER PROBED" in synth, (
        "the synthesizer must be told which dependencies were never probed, so it does not read "
        "their absence from the findings as health"
    )


def test_verdict_precedence_puts_incomplete_first() -> None:
    """A run that lost coverage is not entitled to any complete judgement, good or bad.

    Reporting FRAGILE for a degraded run invites "fix that one exposure and ship"; reporting
    RESILIENT is worse. The verdict is computed in code, so no agent's prose can soften it.
    """
    assert CODE.count("const verdict = ") == 1, "the verdict must be computed in exactly one place"
    line = CODE.split("const verdict = ", 1)[1].splitlines()[0]
    assert line.startswith("unprobed.length || unchecked.length || !synthesis ? 'INCOMPLETE'"), (
        "all three coverage losses must outrank both real verdicts"
    )
    assert "'FRAGILE'" in line and "'RESILIENT'" in line, "the domain verdicts must be named"
    verdict_at = CODE.index("const verdict = ")
    assert "agent(" not in CODE[verdict_at:], "no agent may run after the verdict, let alone produce it"


def test_degraded_items_are_returned_not_just_logged() -> None:
    """A count in log() is not a report — the caller acts on the returned object.

    A result carrying only `exposures` looks complete whatever the log said, so every
    coverage gap travels back in the return value alongside the verdict.
    """
    ret = CODE.split("return {")[-1]
    for key in ("verdict", "exposures", "unprobed", "unchecked", "results", "dependencies", "synthesisRan"):
        assert f"\n  {key},\n" in ret or f"\n  {key}:" in ret, (
            f"the report must expose {key} so the caller can see the gaps"
        )
    assert "synthesisNote:" in ret, "a dead synthesizer must be explained in the result, not only in the log"


def test_every_prompt_is_explicitly_read_only() -> None:
    """A stage named "Probe" does not stop an agent from helpfully fixing what it found.

    This recipe reports and a human fixes; the prohibition has to be in the prompt, in words.
    Probers additionally must not call a third-party API that writes — the failure modes here
    are about payments, webhooks and queues, where a "test" call is a real side effect.
    """
    probe = _segment(CODE, "phase('Probe')", "phase('Synthesize')").lower()
    assert "read-only" in probe, "the prober prompt must say READ-ONLY"
    assert "change nothing" in probe and "commit nothing" in probe
    assert "no third-party api that writes" in probe, "a probe must never write at the provider"

    synth = _segment(CODE, "phase('Synthesize')", "const verdict =").lower()
    assert "read-only" in synth and "change nothing" in synth, "the synthesizer must be read-only too"
    assert "invent nothing" in synth, "an empty shared-fate result must stay a valid answer"


@pytest.mark.parametrize("phase_name", ["Probe", "Synthesize"])
def test_phases_are_announced_at_runtime(phase_name: str) -> None:
    """Progress reporting is how a long fan-out stays legible while it runs."""
    assert f"phase('{phase_name}')" in CODE, f"the {phase_name} stage must call phase()"
