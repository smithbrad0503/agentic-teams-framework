"""The /recipe-new authoring skill must carry the invariants, not just the ceremony.

A recipe that breaks one of these rules does not fail loudly — it returns a
result that looks fine and is not: a sweep that lost a verifier and reported
CLEAN, a batch that authored 7 of 10 and reported success, a resumed run whose
replay diverged from the original. The skill is the only place an author meets
those rules before writing the file, so each one is pinned here.
"""

from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / "skills" / "recipe-new" / "SKILL.md"
SRC = SKILL.read_text(encoding="utf-8")
# Prose is matched against a whitespace-collapsed copy so a phrase that happens to
# wrap across two lines still counts as present.
LOWER = " ".join(SRC.lower().split())
FRONTMATTER = SRC.split("---", 2)[1] if SRC.startswith("---") else ""


def section(heading: str) -> str:
    """The prose of one section, whitespace-collapsed and lowercased.

    Rules are asserted inside the section that states them, not anywhere in the
    file: the worked example repeats several of them verbatim, so a whole-file
    substring check stays green even after the rule itself is deleted.
    """
    assert heading in SRC, f"section heading not found: {heading}"
    body = SRC.split(heading, 1)[1]
    cuts = [body.index(n) for n in ("\n## ", "\n### ") if n in body]
    if cuts:
        body = body[: min(cuts)]
    return " ".join(body.lower().split())


def test_frontmatter_names_the_skill() -> None:
    """The loader keys on `name`; a drift from the directory makes the skill unloadable.

    `skills/recipe-new/SKILL.md` must declare `name: recipe-new` — the same string
    the user types as `/recipe-new`.
    """
    assert SRC.startswith("---"), "SKILL.md must open with YAML frontmatter"
    assert FRONTMATTER, "frontmatter block must be closed"
    assert "name: recipe-new" in FRONTMATTER, "frontmatter name must match the skill directory"
    assert "description:" in FRONTMATTER, "frontmatter must carry a description"


def test_description_is_trigger_rich() -> None:
    """A skill nobody triggers is a skill nobody has.

    The description is the only text the model matches against a user's phrasing,
    so it has to name the slash command AND the natural-language ways the same
    request arrives — "add a recipe", "new workflow script", "automate this
    recurring job".
    """
    desc = FRONTMATTER.split("description:", 1)[1].lower()
    assert "/recipe-new" in desc, "the description must name the slash command"
    for trigger in ("recipe", "workflow script", "create"):
        assert trigger in desc, f"the description must trigger on {trigger!r}"
    assert len(desc.split()) >= 30, "a one-clause description matches almost nothing"


def test_wall_clock_and_randomness_are_forbidden_by_name() -> None:
    """Non-determinism breaks Workflow resume, and the break is invisible.

    A resumed run replays the script; a wall-clock read or an RNG call makes the
    replay diverge from the original, so the second answer differs from the first
    with nothing reporting it. Naming the three constructs explicitly is what lets
    an author recognize them — "avoid non-determinism" does not.
    """
    for banned in ("Date.now()", "Math.random()", "new Date()"):
        assert banned in SRC, f"the skill must name {banned} as forbidden"
    assert "resume" in LOWER, "the skill must say WHY: it breaks Workflow resume"
    assert "args.timestamp" in SRC or "A.timestamp" in SRC, (
        "the skill must show where timestamps come from instead"
    )


def test_meta_must_be_a_pure_literal() -> None:
    """The host parses `meta` without running the script.

    Anything interpolated, computed, or read from `args` inside the literal is
    invisible to the loader, so the recipe advertises itself as something other
    than what it is.
    """
    assert "pure literal" in LOWER, "the skill must require meta to be a pure literal"
    assert "without running the script" in LOWER, "the skill must explain why: meta is parsed, not executed"
    for forbidden in ("interpolation", "function call", "variable"):
        assert forbidden in LOWER, f"the skill must rule out {forbidden}s in the meta literal"
    assert "description" in LOWER and "phases" in LOWER, "required and optional meta fields must be stated"


def test_meta_name_must_equal_the_filename_stem() -> None:
    """A drifted name makes the recipe undiscoverable by the name callers type.

    `Workflow({name: 'foo'})` resolves through the stem; a `meta.name` that says
    something else loads a recipe nobody asked for, or nothing at all. A test in
    tests/test_recipes.py enforces it, so the skill has to say it up front.
    """
    assert "filename stem" in LOWER, "the skill must state the stem-match rule"
    assert "meta.name" in SRC, "the rule must name the field it constrains"


def test_the_script_cannot_be_executed_and_verification_is_structural() -> None:
    """Telling an author to "just run it" sends them into an unfixable error.

    The script references host globals and uses top-level await/return; node and
    pytest both reject it on sight. Verification is assertions against the source
    text, and the skill must say so before the author tries.
    """
    assert "cannot be executed" in LOWER, "the skill must say the script cannot be executed"
    assert "structural" in LOWER, "the skill must say verification is structural"
    for host_global in ("agent", "parallel", "pipeline", "phase", "log", "budget", "args"):
        assert host_global in SRC, f"the host global {host_global!r} must be named"
    assert "top-level" in LOWER, "top-level await/return is half the reason it cannot run"


def test_verdict_and_incomplete_contract_is_present_with_its_history() -> None:
    """`verdict` is the one field a caller reads without knowing the recipe.

    INCOMPLETE is reserved across every recipe for "an agent died, so this is not
    a complete judgement". Six recipes independently invented four spellings of
    that idea before it was pinned, and three defects in this repo trace to the
    same under-modeled thought. Without the history an author reads it as style
    and picks their own word.
    """
    body = section("### 4.5 The verdict, and what INCOMPLETE means")
    assert "every recipe returns a `verdict`" in body, "the verdict contract must be stated"
    assert "`incomplete` is reserved" in body, "INCOMPLETE is not one verdict among many"
    assert "an agent died" in body, "the skill must say what INCOMPLETE is reserved FOR"
    assert "outranks" in body, "INCOMPLETE must outrank the other verdicts, not degrade into them"
    assert "four different spellings" in body, "the skill must carry the history that justifies the rule"
    assert "three separate defects" in body, "the cost paid is what makes the rule stick"
    assert "in code" in body, "the verdict must be computed in code so a dead reporter cannot rewrite it"
    assert "count in `log()` is not a report" in body, "degraded items must be returned, not just logged"


def test_no_silent_drop_rule_is_present_with_the_exact_antipattern() -> None:
    """`.filter(Boolean)` over agent results is how work disappears without a trace.

    `agent()` returns null on no-report and `parallel()`/`pipeline()` resolve a
    thrown thunk to null, so filtering falsy values returns a shorter, cleaner
    report than the run earned — and nothing anywhere says an item was lost. The
    skill has to name the antipattern verbatim and give the two legal recoveries.
    """
    body = section("### 4.6 A dead agent must never silently vanish")
    assert "filter(boolean)" in body, "the exact antipattern must be named"
    assert "without a trace" in body, "the consequence must be stated, not implied"
    assert "returns null" in body, "the skill must explain how nulls arise"
    assert "by index" in body, "index-aligned recovery must be given as the fix"
    assert "never a third state collapsed into a second one" in body, (
        "the rule must be stated as a prohibition, not a suggestion"
    )
    assert "must not be reported as" in body, "the collapse table must state the prohibited reporting"
    for collapsed in ("refuted", "silently exonerates", "reads as success"):
        assert collapsed in body, f"the {collapsed!r} case must appear in the collapse table"


def test_args_normalization_and_pre_spawn_validation_are_required() -> None:
    """Args may arrive as a JSON string, and validation after a spawn is too late.

    Without the guard every `A.<field>` read is undefined and the recipe fans out
    agents against an empty spec; validating after the first `agent()` call has
    already spent money and already dispatched work.
    """
    block = SRC.split("### 4.3 Args contract, normalization, validation", 1)[1].split("\n### ", 1)[0]
    body = " ".join(block.lower().split())
    assert "let a = args || {}" in body, "the normalization guard must be shown as code"
    assert "typeof a === 'string'" in body, "the JSON-string case must be handled"
    assert "json.parse(a)" in body, "the guard must actually parse"
    assert "before the first `agent()` call" in body, "validation must precede the first agent spawn"
    assert "never a throw" in body, "invalid args must return a structured error, not throw"


def test_pipeline_is_the_default_and_parallel_needs_a_barrier() -> None:
    """Reaching for parallel() by reflex is how ordering and recovery are lost.

    `pipeline()` preserves input order, which is exactly what index-aligned
    recovery depends on. `parallel()` earns its place only when a stage genuinely
    needs every prior result at once.
    """
    body = section("## 3. Pattern selection — scaffold from evidence")
    assert "`pipeline()` is the default" in body, "pipeline must be stated as the default"
    assert "genuine barrier" in body, "parallel is only for a genuine barrier"
    assert "preserves input order" in body, "the reason pipeline is the default must be given"


def test_mutation_check_instruction_is_present() -> None:
    """A test whose assertion cannot fail is a green light wired to nothing.

    Structural tests assert on source text, so a typo'd anchor or a mis-scoped
    slice passes forever while asserting nothing. The only proof is to break the
    invariant on purpose and watch the right test go red.
    """
    body = section("### Mutation-check your own tests")
    assert "worse than no test" in body, "the skill must say why a non-failing test is dangerous"
    assert "must fail" in body, "the instruction must state the expected failure"
    assert "break one invariant" in body, "the author must be told to break the invariant deliberately"
    assert "python3 -m pytest -q tests/test_recipe_" in body, "the check must be a runnable command"
    assert ".bak" in body, "the mutation must be reverted afterwards"


def test_write_safety_and_read_only_prompts_are_covered() -> None:
    """A stage named "Audit" does not stop an agent from fixing what it found.

    Read-only is a property of the prompt, in words, or it is not a property at
    all — and a recipe that writes must advertise it in meta.description so a
    caller knows before invoking.
    """
    assert "READ-ONLY" in SRC, "read-only prompts must be shown verbatim"
    assert "every agent prompt" in LOWER, "the prohibition belongs in each prompt, not just one"
    assert "default branch" in LOWER, "writing recipes must be barred from the default branch"
    assert "serialize the writing" in LOWER, "concurrent writers to one file are the batch-author case"


def test_skill_scaffolds_from_the_seven_proven_recipes() -> None:
    """The point of the skill is to copy a shape that survived production.

    An author inventing a shape reinvents the failure modes with it, so pattern
    selection has to name real files the author can open and read.
    """
    body = section("## 3. Pattern selection — scaffold from evidence")
    for recipe in (
        "health-check.js",
        "audit.js",
        "consistency-sweep.js",
        "triage.js",
        "batch-author.js",
        "release-gate.js",
        "retro.js",
    ):
        assert recipe in body, f"the pattern table must point at {recipe}"
    assert "read that file before" in body, "the author must open the model recipe, not just be told its name"
    assert ".claude/workflows/recipes/" in SRC, "the skill must say where recipes live"


def test_test_generation_and_names_registration_are_required() -> None:
    """An unregistered recipe is exempt from every shared invariant test.

    tests/test_recipes.py parametrizes over NAMES; a recipe missing from that list
    is never checked for the meta literal, the stem match, the wall-clock ban, the
    verdict, or INCOMPLETE — the five rules most likely to be broken.
    """
    assert "tests/test_recipes.py" in SRC, "the shared invariant test file must be named"
    assert "NAMES" in SRC, "the registration list must be named"
    assert "tests/test_recipe_" in SRC, "the per-recipe test file convention must be given"
    assert "docstring" in LOWER, "each generated test must explain the failure mode it defends"


def test_verification_step_states_what_cannot_be_verified() -> None:
    """A green suite must not be allowed to imply the recipe works.

    Nothing here spawns an agent, tries a prompt, or exercises a schema against a
    real model. Reporting structural green as if it were runtime evidence is the
    same over-claim the INCOMPLETE verdict exists to prevent.
    """
    body = section("## 6. Verify, and say what you did not verify")
    assert "python3 -m pytest -q" in body, "the verification command must be concrete"
    assert "not verified: any runtime behaviour" in body, (
        "the skill must call out runtime behaviour as unverified, in those words"
    )
    assert "no agent was spawned" in body, "the specific gaps must be named"
    assert "has never run" in body, "the honest claim must be spelled out"


def test_worked_example_is_a_complete_correct_recipe() -> None:
    """The format is easier to copy than to describe.

    A worked example that itself violates an invariant teaches the violation, so
    the example is held to every rule the skill states.
    """
    assert "name: 'link-check'" in SRC, "the example's meta.name must match its stem"
    marker = "export const meta = {\n  name: 'link-check',"
    assert marker in SRC, "the example must open with the meta literal"
    example = SRC.split(marker, 1)[1].split("```", 1)[0]
    # The example's own comments name the antipattern in order to forbid it, so the
    # code-level assertions below run against comment-stripped source.
    code = "\n".join(l for l in example.splitlines() if not l.lstrip().startswith("//"))

    for banned in ("Date.now", "Math.random", "new Date("):
        assert banned not in example, f"the worked example must not use {banned}"
    assert "filter(Boolean)" not in code, "the worked example must not drop dead agents"
    assert "let A = args || {}" in example, "the example must carry the normalization guard"
    assert "return { error: 'link-check:" in example, "the example must validate args before spawning"
    assert "READ-ONLY" in example, "the read-only example must say so in its agent prompt"
    assert "phase('Check')" in example, "the example must announce its phase"
    assert "results.map((r, i)" in example, "the example must recover lost results by index"
    assert "verdict = unchecked.length ? 'INCOMPLETE'" in example, (
        "the example must show INCOMPLETE outranking the domain verdicts"
    )
    assert "verdict," in example.split("return {")[-1], "the example must return the verdict"
