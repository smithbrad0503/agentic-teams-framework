"""batch-author recipe: parallel read-only authoring, ONE serialized writer, no silent drops.

These are structural tests on the source text. The recipe is a Workflow script —
it cannot be imported or executed by node or pytest — so the properties that keep
it correct (a single writer, read-only authors, every target accounted for) have
to be pinned against the file itself, where a future edit that breaks them fails
here instead of in production on someone's i18n catalog.
"""

from pathlib import Path

import pytest

RECIPE = Path(__file__).resolve().parents[1] / ".claude" / "workflows" / "recipes" / "batch-author.js"
SRC = RECIPE.read_text()


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
    """The host reads `meta` without running the script.

    Anything interpolated or computed in the literal is invisible to the loader,
    and a `meta.name` that drifts from the filename stem makes the recipe
    undiscoverable by the name callers actually type.
    """
    assert SRC.startswith("export const meta = {"), "meta must be the first thing in the file"
    assert "name: 'batch-author'" in SRC, "meta.name must equal the filename stem"
    block = SRC.split("export const meta = {", 1)[1].split("\n}\n", 1)[0]
    assert "${" not in block, "meta must be a pure literal — no interpolation"
    assert "args" not in block, "meta must be a pure literal — it cannot read args"
    for title in ("Survey", "Author", "Validate", "Write", "Verify"):
        assert f"title: '{title}'" in block, f"meta.phases must declare the {title} phase"


def test_no_wall_clock_or_randomness() -> None:
    """Non-determinism breaks Workflow resume.

    A resumed run replays the script; a wall-clock read or an RNG call makes the
    replay diverge from the original, so timestamps arrive as args instead.
    """
    for banned in ("Date.now", "Math.random", "new Date("):
        assert banned not in SRC, f"{banned} breaks Workflow resume"
    assert "A.timestamp" in CODE, "the recipe must take its timestamp from args"


def test_args_normalize_from_a_json_string() -> None:
    """The host may hand `args` over as a JSON string rather than an object.

    Without the normalization guard every `A.<field>` read is undefined and the
    recipe would spawn a survey agent against an empty spec.
    """
    assert "let A = args || {}" in CODE
    assert "typeof A === 'string'" in CODE
    assert "JSON.parse(A)" in CODE
    assert "return { error: 'batch-author: args arrived as an unparseable string" in CODE, (
        "unparseable args must return a structured error, not throw"
    )


def test_required_args_are_validated_before_any_agent_spawns() -> None:
    """Validation after the first spawn is validation that already cost money.

    kind, a non-empty targets list, and surveyInstructions are all load-bearing:
    without surveyInstructions the survey agent has nothing to look for, and the
    authors that follow it work blind off whatever it guessed.
    """
    head = CODE.split("agent(", 1)[0]
    for field in ("A.kind", "A.targets", "A.surveyInstructions"):
        assert field in head, f"{field} must be checked before the first agent call"
    assert "Array.isArray(A.targets)" in head, "targets must be checked for being an array"
    assert "!A.targets.length" in head, "an empty targets list must be rejected"
    assert "return { error: 'batch-author: args.kind" in CODE


def test_survey_failure_stops_the_run() -> None:
    """Authors follow the survey spec blind, so no spec means no authoring.

    Proceeding without it would let ten agents invent ten mutually inconsistent
    shapes and hand them to a writer that merges all of them into one file.
    """
    assert "if (!spec) {" in CODE, "a dead survey agent must halt the run"
    stop = _segment(CODE, "if (!spec) {", "phase('Author')")
    assert "return {" in stop and "error:" in stop, "the halt must return a structured error"


def test_single_writer_invariant() -> None:
    """The reason this recipe exists: exactly one agent writes, ever.

    Every entry in a batch lands in the SAME file(s). Fanning the write stage out
    over targets — the obvious-looking "optimization" — produces interleaved,
    conflicting or lost edits, which is precisely what the read-only Author stage
    is protecting against. This test pins the write stage as a serial `for` loop
    over GROUPS with a single awaited agent call inside it, so a future edit that
    wraps it in parallel()/pipeline() or maps it over targets fails here.
    """
    write = _segment(CODE, "phase('Write')", "phase('Verify')")

    assert "parallel(" not in write, "the write stage must never fan out with parallel()"
    assert "pipeline(" not in write, "the write stage must never fan out with pipeline()"
    assert "A.targets" not in write, "the write stage must not iterate targets — it iterates groups"
    assert "Promise.all" not in write, "the write stage must not fan out with Promise.all"

    assert "for (const key of Object.keys(groups))" in write, (
        "the write stage must be a serial for-loop over groups"
    )
    assert write.count("agent(") == 1, "there must be exactly one writer call site in the write stage"
    assert write.count("await agent(") == 1, (
        "the single writer must be awaited inline — an un-awaited call inside the loop "
        "would launch the groups concurrently, which is the exact failure this recipe exists to prevent"
    )
    assert CODE.count("phase: 'Write'") == 1, "only one agent in the whole recipe may carry the Write phase"

    # Nothing may fan out after the writing starts.
    write_at = CODE.index("phase('Write')")
    for fanout in ("parallel(", "pipeline("):
        idx = CODE.rfind(fanout)
        if idx != -1:
            assert idx < write_at, f"{fanout} must not appear at or after the write stage"

    # The writer is told it is alone, so it does not defensively rebase/merge.
    assert "ONLY agent writing these files" in write, "the writer prompt must state that it is the sole writer"


def test_single_writer_reason_is_documented_at_the_write_stage() -> None:
    """The invariant has to survive a reader who does not know the history.

    A silent serial loop looks like an oversight and invites parallelization; the
    comment is the durable half of the guard, so it is pinned too.
    """
    raw_write = SRC.split("phase('Write')", 1)[1].split("phase('Verify')", 1)[0]
    comments = "\n".join(line for line in raw_write.splitlines() if line.lstrip().startswith("//")).lower()
    assert "single-writer invariant" in comments, "the write stage must name the invariant it upholds"
    assert "same file" in comments, "the comment must state WHY: every entry lands in the same file"
    assert "conflict" in comments or "lost" in comments, "the comment must state the failure mode"


def test_grouped_writers_are_serial_not_concurrent() -> None:
    """groupBy is a batching knob, not a parallelism knob.

    Groups exist so a huge batch commits in reviewable chunks; if setting groupBy
    turned N groups into N concurrent writers it would reintroduce the exact
    conflict the single-writer rule removes.
    """
    assert "const groupOf = (t) =>" in CODE, "group keys must come from the target's groupBy field"
    assert "A.groupBy" in CODE
    write = _segment(CODE, "phase('Write')", "phase('Verify')")
    loop_body = write.split("for (const key of Object.keys(groups))", 1)[1]
    assert loop_body.index("await agent(") < loop_body.index("writes.push"), (
        "each group's writer must complete before the loop advances"
    )
    assert "first = false" in loop_body, (
        "only the first writer creates the branch; later groups commit onto it"
    )


def test_authoring_agents_are_explicitly_read_only() -> None:
    """The single-writer rule is only real if the authors honor it.

    N authors that each "helpfully" save their own entry are N concurrent writers
    to one file, whatever the write stage does. The prohibition has to be in the
    prompt, in words, not implied by the stage's name.
    """
    authoring = _segment(CODE, "phase('Author')", "phase('Write')").lower()
    assert "read-only" in authoring, "the authoring prompts must say READ-ONLY"
    assert "do not write" in authoring, "the authoring prompts must forbid writing"
    assert "delete any file" in authoring, "the prohibition must cover every kind of file mutation"
    assert "do not run git" in authoring, "authors must not commit either"
    assert "commit exactly once" not in authoring, "committing belongs to the write stage alone"

    survey = _segment(CODE, "phase('Survey')", "phase('Author')").lower()
    assert "read-only" in survey and "change nothing" in survey, "the survey agent must be read-only too"


def test_survey_must_produce_invariants_with_evidence() -> None:
    """A blind author cannot infer the constraints an existing file already encodes.

    A schema alone yields entries that parse and still violate ranges, key
    formats, ordering or uniqueness. The survey's job is to state those
    constraints with evidence from real rows so the validator has a contract.
    """
    assert "invariants:" in CODE, "the spec schema must carry an invariants field"
    survey = _segment(CODE, "phase('Survey')", "phase('Author')")
    assert "exemplar" in survey, "the spec must include a real exemplar entry"
    assert "min/median/max" in survey, "invariants must be evidenced by real values, not asserted"
    assert "copied verbatim" in survey or "do not invent" in survey, (
        "the exemplar must be drawn from existing entries, not invented"
    )
    assert "validateCommands" in survey, "the survey must identify the commands that validate the file"


def test_validator_may_repair_an_entry_in_place() -> None:
    """Rejecting a mechanically fixable entry wastes a whole authoring round.

    A wrong key format or an out-of-range number is cheaper to correct than to
    re-author, so the validator returns the corrected entry and the batch keeps
    the target instead of losing it.
    """
    assert "fixedEntry" in CODE, "the validation schema must allow an in-place repair"
    assert "JSON.parse(v.fixedEntry)" in CODE, "the repaired entry must actually replace the draft"
    assert "status: repaired ? 'repaired' : 'ok'" in CODE, "a repaired entry must be reported as repaired"


def test_no_target_is_ever_silently_dropped() -> None:
    """A batch that authors 7 of 10 and reports success is the worst outcome here.

    The gap is invisible: the caller sees a green run and a file that is quietly
    missing three entries. So a dead author, a dead validator and a thrown stage
    each get their own status, and every requested target appears in the result.
    """
    assert "filter(Boolean)" not in CODE, (
        "filter(Boolean) over the per-target results is exactly how a dead agent's "
        "target vanishes — reconcile by index instead"
    )
    assert "A.targets.map((t, i)" in CODE, "results must be reconciled against the requested targets by index"
    recovery = CODE.split("A.targets.map((t, i)", 1)[1][:600]
    assert "status: 'failed'" in recovery, "a missing result must become a failed target, not a gap"

    # A dead author and a dead validator are different states, and neither is success.
    assert "if (!draft) return" in CODE, "a dead author must produce a failed outcome"
    assert "status: 'unvalidated'" in CODE, (
        "a dead validator means the invariants were never checked — that is not the "
        "same as checked-and-clean, and it is not the same as rejected"
    )
    assert "'rejected'" in CODE, "an entry that genuinely violates the invariants is rejected, not failed"


def test_failed_targets_are_returned_to_the_caller() -> None:
    """Logging a failure count is not reporting it.

    The caller acts on the returned object; a count that only reaches the run log
    still leaves the batch looking complete to whatever consumes the result.
    """
    returns = [chunk for chunk in CODE.split("return {")[1:] if "requested:" in chunk[:800]]
    assert len(returns) >= 2, "both the nothing-to-write exit and the normal exit must return a report"
    for chunk in returns:
        head = chunk[:1500]
        for key in ("failed:", "unvalidated:", "outcomes:", "requested:"):
            assert key in head, f"every report must expose {key} so the caller can see the gaps"
    assert "requested: A.targets.length" in CODE, (
        "the report must state how many targets were requested, so a short batch is arithmetic, not trust"
    )


def test_dead_writer_and_dead_verifier_are_not_reported_as_success() -> None:
    """The last two places a failure could hide.

    A writer that returns no report may have written nothing, or half a group; a
    verifier that dies has verified nothing. Both must read as unknown-and-flagged
    rather than clean.
    """
    assert "ok: !!report" in CODE, "each write group must record whether its writer reported at all"
    assert "writer agent returned no report" in CODE, "a silent writer must be flagged for hand-checking"
    assert "verify: verify ||" in CODE, "a dead verifier must not collapse into a passing verify"
    fallback = CODE.split("verify: verify ||", 1)[1][:300]
    assert "passed: false" in fallback, "the dead-verifier fallback must not report passed"
    assert "UNVERIFIED" in fallback, "the dead-verifier fallback must say unverified, not failed-clean"


@pytest.mark.parametrize("phase_name", ["Survey", "Author", "Write", "Verify"])
def test_phases_are_announced_at_runtime(phase_name: str) -> None:
    """Progress reporting is how a long batch stays legible while it runs."""
    assert f"phase('{phase_name}')" in CODE, f"the {phase_name} stage must call phase()"
