"""first-run recipe: a discovered journey, one uniform counterfactual, nothing dropped.

Structural tests on the source text. The recipe is a Workflow script — it references
host globals (`agent`, `parallel`, `pipeline`, `phase`, `log`, `args`), uses top-level
`await` and returns at top level, so it cannot be imported or executed by node or by
pytest. The properties that keep it correct are therefore pinned against the file
itself, where an edit that breaks one fails here instead of failing silently in a
report that reads green.

The three ideas this recipe exists to carry, each with a test below: the journey is
discovered rather than declared, one uniform zero-data precondition reaches every
stage, and journey position multiplies severity when findings are ranked.
"""

from pathlib import Path

import pytest

RECIPE = Path(__file__).resolve().parents[1] / ".claude" / "workflows" / "recipes" / "first-run.js"
SRC = RECIPE.read_text(encoding="utf-8")


def _code_only(text: str) -> str:
    """Drop whole-line `//` comments: invariants must hold in code, not in prose."""
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
    `meta.name` that drifts from the filename stem makes the recipe undiscoverable by
    the name callers actually type in `Workflow({name: 'first-run', ...})`.
    """
    assert SRC.startswith("export const meta = {"), "meta must be the first thing in the file"
    assert "name: 'first-run'" in SRC, "meta.name must equal the filename stem"
    block = SRC.split("export const meta = {", 1)[1].split("\n}\n", 1)[0]
    assert "${" not in block, "meta must be a pure literal — no interpolation"
    assert "args" not in block, "meta must be a pure literal — it cannot read args"
    for title in ("Map", "Probe", "Verify", "Rank"):
        assert f"title: '{title}'" in block, f"meta.phases must declare the {title} phase"


def test_meta_advertises_that_the_recipe_never_writes() -> None:
    """A caller decides whether to run this from `meta.description` alone.

    Every stage of this recipe is read-only, and that is a promise a caller should not
    have to open the file to discover. A future edit that adds a writing stage has to
    change this line, which is the point.
    """
    block = SRC.split("export const meta = {", 1)[1].split("\n}\n", 1)[0].lower()
    assert "read-only" in block, "meta.description must state the recipe is read-only"
    assert "never fixes" in block or "never write" in block, "meta must say it reports rather than repairs"


def test_no_wall_clock_or_randomness() -> None:
    """Non-determinism breaks Workflow resume.

    A resumed run replays the script; a wall-clock read or an RNG call makes the replay
    diverge from the original run, and resume then silently produces a different answer
    than the one already reported. Timestamps arrive through args instead.
    """
    for banned in ("Date.now", "Math.random", "new Date("):
        assert banned not in SRC, f"{banned} breaks Workflow resume"
    assert "A.timestamp" in CODE, "the recipe must take its timestamp from args"


def test_ranking_is_deterministic_under_replay() -> None:
    """A replayed sort must produce the same report, not an equivalent one.

    Findings are sorted by a computed score, and equal scores are common (same severity,
    same stage). Without an explicit final tie-break the order depends on the engine's
    sort, so a resumed run can hand the team a differently-ordered "top of the list".
    """
    rank = _segment(CODE, "phase('Rank')")
    assert ".sort((a, b) =>" in rank, "findings must be explicitly sorted"
    assert "a.position - b.position" in rank, "score ties must break on journey position"
    assert "a.title < b.title" in rank, "position ties must break on a stable data field"


def test_args_normalize_from_a_json_string() -> None:
    """The host may hand `args` over as a JSON string rather than an object.

    Without the normalization guard every `A.<field>` read is undefined, the validation
    below passes vacuously on nothing, and the recipe fans probers out against an empty
    spec — an expensive run against a product description that was never delivered.
    """
    assert "let A = args || {}" in CODE
    assert "typeof A === 'string'" in CODE
    assert "JSON.parse(A)" in CODE
    assert "return { error: 'first-run: args arrived as an unparseable string" in CODE, (
        "unparseable args must return a structured error, not throw"
    )
    assert "Array.isArray(A)" in CODE, "an array is not a valid args object either"


def test_required_args_are_validated_before_any_agent_spawns() -> None:
    """Validation after the first spawn is validation that already cost money.

    `product` and `blankSlate` are both load-bearing: without `product` the agents do
    not know what they are reading, and without `blankSlate` the counterfactual has no
    content — the probers reason about "a user" instead of a user with nothing, and a
    product where everything works with data comes back clean.
    """
    head = CODE.split("agent(", 1)[0]
    for field in ("A.product", "A.blankSlate"):
        assert field in head, f"{field} must be checked before the first agent call"
    assert "return { error: 'first-run: args.product is required" in head
    assert "return { error: 'first-run: args.blankSlate is required" in head
    assert "Array.isArray(A.blankSlate)" in head, "blankSlate must accept a list as well as a string"


def test_the_journey_is_discovered_not_declared() -> None:
    """A caller-supplied stage list probes the product they think they shipped.

    The stage nobody remembered to list is exactly where a new user stalls, so the
    ordered journey is an output of the Map agent reading the code — never an arg. This
    pins that no stage list can sneak into the args contract.
    """
    assert "A.stages" not in CODE, "journey stages must never arrive as an arg"
    assert "A.journey" not in CODE, "journey stages must never arrive as an arg"
    assert "journey.stages" in CODE, "the stages must come from the Map agent's report"
    mapping = _segment(CODE, "const mapPrompt", "const probePrompt").lower()
    assert "discover it from the code" in mapping, "the Map agent must be told to derive the journey, not assume one"
    assert "ordered stages" in mapping, "journey order is load-bearing for ranking, so it must be requested"


def test_one_uniform_precondition_reaches_every_stage() -> None:
    """The counterfactual is the recipe. Applied unevenly, it finds nothing.

    "Assume zero data, no prior state, nothing seeded" is what makes defects of absence
    visible; an agent without it reasons about a populated account, where everything
    works. So the same PREAMBLE is prepended to the mapper, every prober, and every
    verifier — a verifier handed only the claim re-reads the code as a normal user and
    "refutes" a real defect.
    """
    assert CODE.count("PREAMBLE") >= 4, "the preamble must be defined once and used by all three prompts"
    preamble = _segment(CODE, "const PREAMBLE =", "const mapPrompt")
    assert "ZERO DATA and NO PRIOR STATE" in preamble, "the precondition must be stated in the shared preamble"
    assert "${BLANK}" in preamble, "the caller's concrete blank-slate description must reach the agents"
    for prompt_start, prompt_end in (
        ("const mapPrompt", "const probePrompt"),
        ("const probePrompt", "const verifyPrompt"),
        ("const verifyPrompt", "phase('Map')"),
    ):
        body = _segment(CODE, prompt_start, prompt_end)
        assert "${PREAMBLE}" in body, f"{prompt_start} must carry the shared precondition"


def test_every_agent_prompt_is_read_only() -> None:
    """A stage named "Probe" does not stop an agent from helpfully fixing what it found.

    Read-only is a property of the prompt, in words, or it is not a property at all.
    Because all three prompts inherit the shared preamble, the prohibition lives there
    once and cannot be dropped from one stage by accident.
    """
    preamble = _segment(CODE, "const PREAMBLE =", "const mapPrompt")
    assert "READ-ONLY" in preamble, "the shared preamble must say READ-ONLY"
    assert "Change NOTHING" in preamble, "the prohibition must be explicit"
    assert "commit NOTHING" in preamble, "read-only must cover git, not just the editor"
    verify = _segment(CODE, "const verifyPrompt", "phase('Map')")
    assert "READ-ONLY" in verify, "the verifier repeats the prohibition where it is easiest to forget"


def test_a_dead_mapper_halts_the_run_as_incomplete() -> None:
    """Zero stages must never fall through into zero findings.

    Probing an empty stage list spawns nothing, finds nothing, and returns an empty
    findings array — a clean bill of health for a product whose first-run path was never
    read. The run stops, and it stops as INCOMPLETE rather than as an error a caller
    might read as "nothing wrong".
    """
    assert "if (!journey || !Array.isArray(journey.stages) || !journey.stages.length) {" in CODE
    halt = _segment(CODE, "if (!journey || !Array.isArray(journey.stages) || !journey.stages.length) {", "phase('Probe')")
    assert "verdict: 'INCOMPLETE'" in halt, "a dead mapper must return the reserved verdict"
    assert "error:" in halt, "the halt must return a structured error naming what died"
    assert "agent(" not in halt, "nothing may be probed after the journey failed to map"


def test_no_stage_is_silently_dropped() -> None:
    """A stage that was never probed must not read as a stage with nothing wrong.

    `pipeline` yields null where a stage thunk threw, and a prober can return no report
    at all. Both are absences of evidence, and both look identical to "clean" once they
    are filtered out — the report comes back shorter and greener than the product is,
    with nothing anywhere saying so.
    """
    assert "filter(Boolean)" not in CODE, (
        "filter(Boolean) over the per-stage results is exactly how a whole journey stage "
        "vanishes — recover by index instead"
    )
    assert "probes.map((p, i)" in CODE, "stage results must be reconciled against `stages` by index"
    recovery = CODE.split("probes.map((p, i)", 1)[1][:400]
    assert "stages[i].name" in recovery, "a lost result must be named for the stage it came from"
    assert "unprobed: true" in recovery, "a lost stage must become an explicit unprobed entry"
    probe = _segment(CODE, "phase('Probe')", "const settled")
    assert "if (!r || !Array.isArray(r.issues)) {" in probe, "a prober that reported nothing must be caught too"
    assert probe.count("unprobed: true") == 1, "the no-report case must produce an unprobed entry, not an empty list"


def test_a_dead_verifier_is_not_a_refutation() -> None:
    """Fails OPEN if collapsed: a crashed verifier would exonerate a real defect.

    Verification here is adversarial, so a falsy result means "not a real problem" and
    the finding is dropped from the report. A null agent result must therefore be its own
    third state, and a thrown verifier thunk must be recovered by index rather than
    filtered out of the array.
    """
    assert "v ? (v.refuted ? 'refuted' : 'confirmed') : 'unverified'" in CODE, (
        "confirmed | refuted | unverified must be three states, not two"
    )
    verify = _segment(CODE, "return parallel(", "const settled")
    assert "map((v, idx) =>" in verify, "a thrown verifier thunk must be recovered by index"
    assert "verdict: 'unverified'" in verify, "the recovered entry must be unverified, not refuted"
    assert "serious[idx]" in verify, "the recovered entry must keep the finding it came from"


def test_unchallenged_polish_is_not_confused_with_a_dead_verifier() -> None:
    """Two different absences of a verdict, only one of which is a degraded run.

    Polish findings skip verification by policy — reading them costs less than checking
    them. That is a deliberate choice and must not spend the INCOMPLETE verdict, which is
    reserved for an agent that died. Spelling both "unverified" would make every run with
    a cosmetic nit report as a run that lost coverage.
    """
    assert "verdict: 'unchallenged'" in CODE, "policy-skipped findings need their own state"
    verdict_line = [line for line in CODE.splitlines() if line.startswith("const verdict =")]
    assert len(verdict_line) == 1, "there must be exactly one verdict computation"
    assert "unchallenged" not in verdict_line[0], "an unchallenged polish nit must not make the run INCOMPLETE"
    assert "unverified.length" in verdict_line[0], "a dead verifier must make the run INCOMPLETE"


def test_incomplete_outranks_every_other_verdict() -> None:
    """A run that lost coverage is not entitled to a complete judgement, good or bad.

    Reporting a degraded run as BLOCKED invites "fix that one blocker and ship" — the
    path that must never open, because the stages nobody probed are still unknown. So
    INCOMPLETE is tested first, and the verdict is computed in code: a dead reporting
    agent cannot turn an INCOMPLETE into something more comfortable.
    """
    verdict_line = [line for line in CODE.splitlines() if line.startswith("const verdict =")][0]
    order = [verdict_line.index(v) for v in ("'INCOMPLETE'", "'BLOCKED'", "'ROUGH'", "'READY'")]
    assert order == sorted(order), "INCOMPLETE must be decided before BLOCKED, ROUGH or READY"
    assert "unprobed.length" in verdict_line, "a stage never probed must force INCOMPLETE"
    rank = _segment(CODE, "phase('Rank')")
    assert "agent(" not in rank, "the verdict must be computed in code, never delegated to an agent"


def test_journey_position_multiplies_severity() -> None:
    """A defect at step 1 blocks every user; the same defect at step 9 blocks the few
    who got there — and they got there, so the product already worked for them.

    Position has to be a multiplier rather than a tie-break after severity: sorting by
    severity alone puts a late blocker above an early major and sends the team to fix
    the defect fewer people ever reach.
    """
    rank = _segment(CODE, "phase('Rank')")
    assert "SEV_WEIGHT" in rank, "severity must carry a numeric weight to be multiplied"
    assert "(SEV_WEIGHT[f.severity] || 1) * ((TOTAL - position) / TOTAL)" in rank, (
        "the score must multiply severity weight by journey position, not order by severity then position"
    )
    assert "stageOrder[s.name] = idx" in rank, "position must come from the discovered journey order"
    assert "TOTAL - 1" in rank, "a finding whose stage cannot be placed must rank as the latest stage, not the earliest"


def test_degraded_items_are_returned_not_just_logged() -> None:
    """The caller acts on the returned object; a count in the run log is not a report.

    An unverified finding is the one most likely to be both real and unattended, and a
    stage nobody probed is the gap the caller most needs to see. Both ride in the result
    alongside explicit coverage arithmetic, so a short run is visible without trust.
    """
    final = CODE.split("return {")[-1]
    for key in ("unverified,", "unprobed,", "coverage:", "refutedCount,"):
        assert key in final, f"the report must expose {key} so the caller can see the gaps"
    assert "stagesRequested: stages.length" in final, (
        "coverage must state how many stages were requested, so a short run is arithmetic, not trust"
    )
    assert "stagesProbed: settled.length - unprobed.length" in final


@pytest.mark.parametrize("phase_name", ["Map", "Probe", "Rank"])
def test_phases_are_announced_at_runtime(phase_name: str) -> None:
    """Progress reporting is how a long fan-out stays legible while it runs."""
    assert f"phase('{phase_name}')" in CODE, f"the {phase_name} stage must call phase()"


def test_verification_agents_are_tagged_with_their_own_phase() -> None:
    """Verify runs interleaved inside Probe, so it is a label rather than a phase() call.

    Without the tag every verifier reports as part of the Probe stage and the run log
    cannot distinguish "still probing" from "challenging what was found".
    """
    assert "phase: 'Verify'" in CODE, "verifier agents must carry the Verify phase label"
    assert CODE.count("phase: 'Verify'") == 1, "there is exactly one verifier call site"
