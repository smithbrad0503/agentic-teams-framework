"""state-reconcile recipe: two BLIND gatherers, drift, and a bounded opt-in write-back.

Structural tests on the source text. The recipe is a Workflow script — it references
host globals (`agent`, `parallel`, `phase`, `log`, `args`) and uses top-level await
and top-level return — so it cannot be imported or executed by node or by pytest, and
the properties that keep it correct are pinned against the file itself.

Two properties carry this recipe and are the reason most of these tests exist:

1. **Blind independence.** Drift is only trustworthy if the claim picture and the
   reality picture were formed without either seeing the other. An agent shown the
   board first rationalizes the git history until it matches, and the resulting drift
   list measures the agent's agreeableness rather than the project. Independence is
   enforced three ways — temporally, lexically, and in words — and each is pinned
   separately here so that breaking one still turns something red.

2. **An absent gatherer looks exactly like agreement.** One missing picture produces
   an empty diff, which is shape-identical to perfect alignment. That must be
   INCOMPLETE with `drift: null`, never ALIGNED and never `drift: []`.
"""

from pathlib import Path

RECIPE = (
    Path(__file__).resolve().parents[1]
    / ".claude"
    / "workflows"
    / "recipes"
    / "state-reconcile.js"
)
SRC = RECIPE.read_text(encoding="utf-8")


def _code_only(text: str) -> str:
    """Drop whole-line `//` comments: invariants must hold in code, not in prose.

    This recipe's comments deliberately quote the antipatterns they forbid, so a
    whole-file substring check would pass on a file that only *talks* about the rule.
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


# --- the shared recipe contract --------------------------------------------


def test_meta_is_a_pure_literal_named_for_the_file() -> None:
    """The host parses `meta` without running the script.

    Anything interpolated or read from `args` inside the literal is invisible to the
    loader, and a `meta.name` that drifts from the filename stem makes the recipe
    undiscoverable by the name callers actually type in `Workflow({name: ...})`.
    """
    assert SRC.startswith("export const meta = {"), "meta must be the first thing in the file"
    assert "name: 'state-reconcile'" in SRC, "meta.name must equal the filename stem"
    block = SRC.split("export const meta = {", 1)[1].split("\n}\n", 1)[0]
    assert "${" not in block, "meta must be a pure literal — no interpolation"
    assert "args" not in block, "meta must be a pure literal — it cannot read args"
    assert "Report-only by default" in block, (
        "meta.description must advertise that this recipe defaults to writing nothing — "
        "a caller decides whether to invoke it from the description alone"
    )


def test_no_wall_clock_and_no_randomness_anywhere_including_comments() -> None:
    """A resumed Workflow replays the script; a clock or RNG read makes it diverge.

    This recipe judges *staleness*, so a wall-clock read would make a replay disagree
    with the original run about what is stale — the failure would be invisible and
    would land in exactly the field the recipe exists to compute. tests/test_recipes.py
    greps raw source, comments included, so the tokens cannot appear even in prose.
    """
    for banned in ("Date.now", "Math.random", "new Date("):
        assert banned not in SRC, f"{banned} breaks Workflow resume"
    assert "A.asOf || A.timestamp" in CODE, "the staleness clock must arrive through args"
    assert "args.timestamp required" in SRC, "timestamp must be a hard requirement, not a default"


def test_args_are_normalized_then_validated_before_any_agent_spawns() -> None:
    """Some hosts deliver args as a JSON string, and late validation costs money.

    Without the string guard every `A.<field>` read is undefined and the recipe
    reconciles two empty specs into a confident "no drift". Validating after the first
    spawn has already paid for two high-effort agents and already told them to work.
    """
    assert "let A = args || {}" in CODE, "the normalization guard must be present"
    assert "typeof A === 'string'" in CODE, "the JSON-string case must be handled"
    assert "JSON.parse(A)" in CODE, "the guard must actually parse"
    spawn = CODE.index("await parallel(")
    errors = [i for i in range(len(CODE)) if CODE.startswith("return { error: 'state-reconcile:", i)]
    assert errors, "invalid args must return a structured error"
    assert max(errors) < spawn, "every args validation must precede the first agent spawn"
    assert "throw" not in CODE, "invalid args must return a structured error, never throw"
    for required in ("args.subject", "args.claim.instructions", "args.reality.instructions"):
        assert required in SRC, f"{required} must be validated by name"


# --- blind independence: three independent enforcements ---------------------


def test_blindness_is_enforced_temporally_by_a_single_parallel_call() -> None:
    """Sequential awaits are how a future edit casually destroys independence.

    Both gatherers must be in flight at the same time, handed to ONE `parallel()`
    call. If someone rewrites this as `await agent(CLAIM_PROMPT)` followed by
    `await agent(REALITY_PROMPT)`, the second prompt *can* be fed the first result
    and nothing else in the file would object — the recipe would keep returning a
    drift list that is really a measure of the second agent's agreeableness.
    """
    assert CODE.count("await parallel(") == 1, "exactly one parallel barrier: the double-gather"
    fanout = _segment(CODE, "await parallel([", "\n])")
    assert "agent(CLAIM_PROMPT" in fanout, "the claim gatherer must run inside the barrier"
    assert "agent(REALITY_PROMPT" in fanout, "the reality gatherer must run inside the barrier"
    assert "await agent(CLAIM_PROMPT" not in CODE, "a sequential await breaks the double-gather"
    assert "await agent(REALITY_PROMPT" not in CODE, "a sequential await breaks the double-gather"
    assert "const [claimSide, realitySide] = await parallel([" in CODE, (
        "both results must be destructured from the one barrier"
    )


def test_blindness_is_enforced_lexically_by_the_temporal_dead_zone() -> None:
    """Both prompts are frozen before either result binding exists.

    `claimSide` and `realitySide` are declared by the `const [...] = await parallel(...)`
    line, so inside the prompt constants above it they are in the temporal dead zone.
    An edit that interpolates one gatherer's result into the other's prompt is then a
    ReferenceError on the first run rather than a silent bias nobody can see in the
    output. This test pins the ordering that makes that true.
    """
    # Indices are taken against comment-stripped code on purpose: the recipe's own
    # comment quotes the destructuring line to explain this rule, and matching that
    # prose would make the ordering assertion pass or fail on where a comment sits.
    claim_at = CODE.index("const CLAIM_PROMPT =")
    reality_at = CODE.index("const REALITY_PROMPT =")
    results_at = CODE.index("const [claimSide, realitySide]")
    assert claim_at < reality_at < results_at, (
        "both prompts must be constructed BEFORE the result bindings are declared"
    )
    prompts = CODE[claim_at:results_at]
    assert "claimSide" not in prompts, "no prompt may read the claim gatherer's result"
    assert "realitySide" not in prompts, "no prompt may read the reality gatherer's result"


def test_blindness_is_enforced_in_words_in_each_gatherer_prompt() -> None:
    """A curious agent reads the other side's sources unless told not to.

    Structure keeps the results apart; only the prompt keeps the *agent* away from
    the other side's raw sources. The claim gatherer must be barred from corroborating
    against reality, and the reality gatherer must be barred from treating any record
    as evidence — otherwise both agents converge on the same document and the diff is
    empty for the worst possible reason.
    """
    claim_prompt = _segment(SRC, "const CLAIM_PROMPT =", "const REALITY_PROMPT =")
    reality_prompt = _segment(SRC, "const REALITY_PROMPT =", "phase('Gather')")

    assert "BLIND:" in claim_prompt, "the claim gatherer must be told it is blind"
    assert "Do NOT inspect git history" in claim_prompt, "it must be barred from reality's sources"
    assert "corroborate NOTHING" in claim_prompt, "it must not check the record it is transcribing"

    assert "BLIND:" in reality_prompt, "the reality gatherer must be told it is blind"
    assert "Do NOT open the board" in reality_prompt, "it must be barred from the claim's sources"
    assert "is not evidence" in reality_prompt, "a record must never be usable as evidence"


def test_only_the_reconciler_sees_both_pictures_and_not_the_authorized_fields() -> None:
    """A drift list tailored to what may be written is a shorter drift list.

    The reconciler is the first agent allowed both pictures, but it must not be told
    which fields the caller authorized: an agent that knows only `status` is writable
    quietly stops reporting drift it cannot fix, and the unauthorized findings are
    exactly the ones a human needs. Authorization is applied in code, afterwards.
    """
    reconcile_prompt = _segment(SRC, "const rec = await agent(", "{ label: 'reconcile'")
    assert "gathered INDEPENDENTLY and BLIND" in reconcile_prompt, (
        "the reconciler must be told the disagreement is real signal, not a coordination artifact"
    )
    assert "ALLOWED" not in reconcile_prompt, "the reconciler must not see the authorized field list"
    assert "authorizedFields" not in reconcile_prompt
    assert SRC.index("const rec = await agent(") < SRC.index("const authorized ="), (
        "the drift list must be complete before authorization filters it"
    )


# --- a dead agent must never read as agreement -----------------------------


def test_a_dead_gatherer_is_incomplete_and_never_no_drift() -> None:
    """This is the recipe's sharpest failure mode: absence is shaped like agreement.

    One missing picture yields an empty diff. Returning `drift: []` with a domain
    verdict would report a reconciliation that reconciled nothing as a clean bill of
    health — the same class of defect as filtering dead agents out and printing "ALL
    GATES GREEN". `drift: null` is unmistakably "not computed"; `[]` is a claim that
    the diff ran and found nothing.
    """
    assert "filter(Boolean)" not in CODE, "recover explicitly, never filter dead agents out"
    block = _segment(CODE, "if (lost.length) {", "const claims = claimSide.claims")
    assert "verdict: 'INCOMPLETE'" in block, "a lost gatherer must yield INCOMPLETE"
    assert "drift: null" in block, "an uncomputed diff must be null, never an empty array"
    assert "drift: []" not in block, "an empty drift array here would read as agreement"
    assert "'ALIGNED'" not in block, "a half-gathered run must never reach a domain verdict"
    assert "lost.push({ side: 'claim'" in CODE, "the dead claim gatherer must be named in the result"
    assert "lost.push({ side: 'reality'" in CODE, "the dead reality gatherer must be named in the result"


def test_a_dead_reconciler_is_also_incomplete_and_returns_the_raw_pictures() -> None:
    """A reconciler that died did not find zero drift; it found nothing at all.

    Same collapse one stage down. The two gathered pictures are returned raw so the
    run is not a total loss and a human can do the diff by eye, but the verdict must
    still refuse to be a judgement the run did not earn.
    """
    block = _segment(CODE, "if (!rec) {", "const drift = rec.drift")
    assert "verdict: 'INCOMPLETE'" in block, "a dead reconciler must yield INCOMPLETE"
    assert "drift: null" in block, "an uncomputed diff must be null, never an empty array"
    assert "drift: []" not in block, "an empty drift array here would read as agreement"
    assert "gathered:" in block, "the raw pictures must survive so the run is salvageable by hand"


def test_a_dead_writer_is_lost_coverage_of_the_working_tree() -> None:
    """`wrote: null` must never be read as "wrote nothing".

    A writer that returned no report may have applied some, all, or none of the
    corrections. That is lost coverage of the files themselves, so it must degrade the
    verdict rather than silently look like a run that chose not to write.
    """
    assert "if (!wrote) lost.push({ side: 'write'" in CODE, (
        "a writer with no report must be recorded as a lost stage, not an absent write"
    )
    assert "may be partially edited" in SRC, "the reason must say what a human has to go check"


def test_verdict_is_computed_in_code_with_incomplete_outranking() -> None:
    """`verdict` is the one field a caller reads without knowing the recipe.

    INCOMPLETE is reserved across every recipe for "an agent died, so this is not a
    complete judgement", and it must outrank both domain verdicts — computed in code,
    never asked of an agent, so a dead reporting stage cannot upgrade an INCOMPLETE
    into something more comfortable.
    """
    assert (
        "const verdict = lost.length ? 'INCOMPLETE' : drift.length ? 'DRIFTED' : 'ALIGNED'" in CODE
    ), "INCOMPLETE must be tested first, in code"
    tail = SRC.split("return {")[-1]
    for field in ("verdict,", "drift,", "withheld,", "lost,", "unreadable,"):
        assert field in tail, f"the caller acts on the returned object — {field!r} must be in it"


def test_degraded_and_unauthorized_items_are_returned_not_just_logged() -> None:
    """A count in `log()` is not a report.

    Unreadable sources, low-confidence drift, and drift the caller did not authorize
    are all things a human must see. Partitioning `drift` into authorized/withheld is
    only safe because BOTH halves come back; the moment one is dropped, the recipe is
    quietly deciding what the human is allowed to know about.
    """
    assert "const withheld = drift" in CODE, "unauthorized drift must be captured, not discarded"
    assert "withheldReason" in CODE, "each withheld item must say why it was not written"
    assert "unreadable" in CODE, "sources neither side could read must be surfaced"
    assert "treat as unknown, never as agreement" in SRC, (
        "the reconciler must not read an unreadable source as concord"
    )


# --- write-back: opt-in, bounded, single writer -----------------------------


def test_write_back_is_opt_in_and_defaults_to_reporting_only() -> None:
    """Tracking state is human-curated; rewriting it by default destroys the signal.

    This repeats a decision already made in scripts/run_metrics.py, whose `--reconcile`
    reports board-vs-PR disagreements and deliberately never writes board.json. A
    recipe that "fixed" the board would delete the very disagreement it was built to
    surface, and would do it invisibly.
    """
    assert "const ALLOWED = WB ? WB.fields.map(String) : []" in CODE, (
        "with no writeBack the authorized field list must be empty"
    )
    assert "if (ALLOWED.length && authorized.length) {" in CODE, (
        "the Write stage must be gated on explicit authorization AND something to write"
    )
    assert "mode: ALLOWED.length ? 'write-back' : 'report-only'" in CODE, (
        "the result must state which mode the run was in"
    )
    assert "report-only" in SRC.split("export const meta = {", 1)[1].split("\n}\n", 1)[0].lower()


def test_write_back_must_name_its_fields_and_an_empty_opt_in_is_an_error() -> None:
    """`writeBack: {}` is a caller who wants writes but has not said which.

    Treating that as "write everything" is the wholesale overwrite this recipe exists
    to refuse; treating it as "write nothing" silently ignores an explicit request.
    Both are wrong, so it is a validation error before anything spawns.
    """
    assert "args.writeBack.fields must be a non-empty array" in SRC, (
        "an opt-in without named fields must be rejected"
    )
    assert "never writes anything a caller did not name" in SRC, "the rule must be stated in the error"
    assert CODE.index("args.writeBack.fields must be a non-empty array") < CODE.index(
        "await parallel("
    ), "the writeBack shape must be validated before any agent spawns"
    assert "ALLOWED.indexOf(String(d.field)) >= 0" in CODE, (
        "only drift whose field the caller named may be written"
    )


def test_the_writer_is_single_bounded_and_barred_from_the_default_branch() -> None:
    """Concurrent writers to one file interleave and lose edits; a broad writer overwrites.

    The write stage must be exactly one serialized agent, told the precise fields it
    may touch, forbidden from wholesale rewrites and from "fixing" anything else it
    notices, and forbidden from committing to the default branch or touching a PR.
    """
    write_stage = _segment(SRC, "phase('Write')", "{ label: 'write:state'")
    assert "parallel(" not in write_stage, "there must be exactly ONE writer — never a fan-out"
    assert "pipeline(" not in write_stage, "there must be exactly ONE writer — never a fan-out"
    assert "## The ONLY fields you may change" in write_stage, "the writer must be handed its bounds"
    assert "ALLOWED.join" in write_stage, "the bounds must be the caller's actual field list"
    assert "Edit ONLY the fields listed above" in write_stage
    assert "Never rewrite or regenerate a whole file" in write_stage, "no wholesale overwrite"
    assert "You are the ONLY agent writing these files in this run" in write_stage
    assert "Do NOT commit or push to the default branch" in write_stage
    assert "do NOT open a PR" in write_stage and "do NOT merge a PR" in write_stage
    assert "touchedOutsideAuthorization" in write_stage, (
        "an over-broad edit must be reportable rather than concealed"
    )
    assert "notApplied" in write_stage, "an authorized correction that was not made must be named"


def test_every_read_only_stage_says_read_only_in_its_own_prompt() -> None:
    """A stage named "Gather" does not stop an agent from helpfully fixing what it found.

    Read-only is a property of the prompt, in words, or it is not a property at all.
    All three non-writing stages state it individually — a single mention at the top
    of the file constrains nothing.
    """
    for start, end in (
        ("const CLAIM_PROMPT =", "const REALITY_PROMPT ="),
        ("const REALITY_PROMPT =", "phase('Gather')"),
        ("const rec = await agent(", "{ label: 'reconcile'"),
    ):
        assert "READ-ONLY:" in _segment(SRC, start, end), f"{start} must declare itself read-only"


def test_the_stages_are_gather_reconcile_write_and_nothing_else() -> None:
    """The framework already ships a `retro` recipe; a near-duplicate is worse than nothing.

    The source this was derived from ended with its own retro stage. Two recipes that
    both write retrospectives drift apart, and callers cannot tell which one to run.
    Pinning the stage list keeps that stage from creeping back in, and keeps meta.phases
    honest about what a long run is actually doing.
    """
    import re

    assert re.findall(r"phase\('(\w+)'\)", CODE) == ["Gather", "Reconcile", "Write"], (
        "exactly three stages, in this order"
    )
    block = SRC.split("export const meta = {", 1)[1].split("\n}\n", 1)[0]
    assert re.findall(r"title: '(\w+)'", block) == ["Gather", "Reconcile", "Write"], (
        "meta.phases must match the stages the code actually announces"
    )
