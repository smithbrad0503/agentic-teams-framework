"""Structural pins for the `triage` recipe.

Workflow scripts run inside the host harness (globals `agent`, `pipeline`, `phase`,
`log`, `args`, top-level `await`/`return`), so they cannot be imported by pytest or
executed by node. Everything here is asserted against the source text — which is
enough to pin the properties that make this recipe safe to point at anything.
"""

import re
from pathlib import Path

RECIPE = Path(__file__).resolve().parents[1] / ".claude" / "workflows" / "recipes" / "triage.js"
SRC = RECIPE.read_text()


def _brace_block(src: str, start: int) -> str:
    """Return the balanced {...} block beginning at or after `start`."""
    i = src.index("{", start)
    depth = 0
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[i : j + 1]
    raise AssertionError(f"unbalanced braces from offset {start}")


def _agent_prompts() -> list[str]:
    """Text of each agent() call from the open paren up to its options object."""
    prompts = []
    for m in re.finditer(r"(?<![\w.])agent\(", SRC):
        prompts.append(SRC[m.end() : SRC.index("{ label:", m.end())])
    return prompts


def test_meta_is_a_pure_literal_named_for_its_file() -> None:
    """The dispatcher reads `meta` statically to list recipes.

    It never runs the script, so anything computed — a variable, a call, an
    interpolation — reads as literal source text and the recipe becomes
    undiscoverable or mislabelled. `meta.name` must also equal the filename stem,
    because that stem is how a caller asks for this recipe.
    """
    assert "export const meta = {" in SRC, "missing meta export"
    block = _brace_block(SRC, SRC.index("export const meta ="))
    assert "name: 'triage'" in block, "meta.name must equal the filename stem 'triage'"
    assert "${" not in block, "meta must be a pure literal — no template interpolation"
    assert not re.search(r"\w\(", block), "meta must be a pure literal — no function calls"
    for title in ("Split", "Diagnose", "Consolidate"):
        assert f"title: '{title}'" in block, f"meta.phases must declare the {title} phase"


def test_no_wall_clock_or_random_calls() -> None:
    """Workflow resume replays the script; nondeterminism breaks it.

    `Date.now()`, `Math.random()` and argless `new Date()` return different values
    on replay, so a resumed run diverges from the run it is resuming. The timestamp
    is passed in by the dispatcher instead.
    """
    for banned in ("Date.now", "Math.random", "new Date("):
        assert banned not in SRC, f"{banned} breaks Workflow resume"
    assert "A.timestamp" in SRC, "timestamp must come from args, not from a clock"


def test_args_are_normalized_and_validated_before_any_agent_spawns() -> None:
    """Bad input must cost zero agent spawns, and args can arrive as a string.

    The harness sometimes hands over a JSON string rather than an object; without
    the parse shim every property read silently yields undefined and the run fans
    out agents against an empty report. Validation returns `{error}` rather than
    throwing, so the dispatcher gets a readable result.
    """
    assert "typeof A === 'string'" in SRC, "missing the string-args normalization shim"
    assert "JSON.parse(A)" in SRC, "string args must be parsed, not assumed to be an object"
    assert "args arrived as an unparseable string" in SRC, "unparseable args must return an error"
    assert "!A.report" in SRC, "args.report must be validated as required"
    assert SRC.index("!A.report") < SRC.index("agent("), "validation must precede the first agent spawn"


def test_taxonomy_is_parameterized_not_hardcoded() -> None:
    """The recipe must work on any project, not the one it was harvested from.

    Categories and severities are caller-supplied with generic defaults, and the
    diagnosis schema must reference those variables — inlining an enum in the
    schema would silently ignore whatever the caller passed.
    """
    assert "['BUG', 'UX', 'DESIGN', 'DATA', 'PERF', 'UNCLEAR']" in SRC, "missing default categories"
    assert "['BLOCKS_CORE_FLOW', 'DEGRADES', 'POLISH', 'NICE_TO_HAVE']" in SRC, "missing default severities"
    diagnosis = _brace_block(SRC, SRC.index("const DIAGNOSIS_SCHEMA"))
    assert "enum: CATEGORIES" in diagnosis, "kind must use the caller-supplied categories"
    assert "enum: SEVERITIES" in diagnosis, "severity must use the caller-supplied severities"
    assert "trackedDebt" in SRC, "known issues must be accepted so they are not re-diagnosed as new"
    assert "do NOT re-diagnose" in SRC, "the tracked-debt rule must reach the agents' prompt"


def test_every_agent_prompt_declares_read_only() -> None:
    """Read-only throughout is this recipe's entire value proposition.

    It is safe to point at any repo, any branch, any production checkout precisely
    because no stage may modify code. That guarantee lives only in the prompts, so
    an added stage that forgets the instruction silently removes it.
    """
    prompts = _agent_prompts()
    assert len(prompts) == 3, f"expected Split/Diagnose/Consolidate agents, found {len(prompts)}"
    for i, prompt in enumerate(prompts):
        assert "READ-ONLY" in prompt, f"agent call #{i + 1} does not declare READ-ONLY"
        assert "change NOTHING" in prompt, f"agent call #{i + 1} does not forbid modification"


def test_a_dead_diagnosing_agent_cannot_drop_an_item() -> None:
    """An item whose agent died must surface as undiagnosed, never vanish.

    A null agent result mapped through a truthiness filter disappears, and the
    triage then reports a shorter, cleaner list than the human actually reported —
    the failure mode fails OPEN, exactly the bug `audit.js` was patched for. Both
    layers must recover: the `.then` (agent returned null) and the array map (the
    thunk itself threw).
    """
    assert "undiagnosed: true, reason:" in SRC, "a null diagnosis must become an undiagnosed record"
    assert not re.search(r"(diagnosed|settled)\s*\.filter\(Boolean\)", SRC), (
        "filtering nulls out of the diagnosis results is how items silently disappear"
    )
    assert re.search(r"\.then\(\(d\) => \(d \? \{ item, \.\.\.d \} : \{ item, undiagnosed: true", SRC), (
        "a null agent report must be recovered inside .then, not collapsed to null"
    )
    assert re.search(r"\.map\(\(d, i\) => d \|\| \{ item: items\[i\]", SRC), (
        "an errored thunk resolves to null one layer out and must be recovered too"
    )
    assert "undiagnosed.length === 0" in SRC, "the result must report whether coverage was complete"


def test_a_dead_split_agent_returns_the_raw_report_rather_than_an_empty_triage() -> None:
    """Zero items from the splitter is not a clean report.

    Falling through would produce four empty lists — a clean bill of health for a
    report nobody ever read. The raw text must come back as undiagnosed so the
    human's words survive the failure.
    """
    guard = SRC.index("if (!split")
    block = _brace_block(SRC, guard)
    assert "undiagnosed: [{ item: raw" in block, "the raw report must be surfaced when the splitter dies"
    assert "error:" in block, "a failed split must be reported as an error, not as a successful triage"
    assert guard < SRC.index("phase('Diagnose')"), "the split guard must run before diagnosis"


def test_keep_protect_mechanic_survives_to_the_output() -> None:
    """Reclassifying "I like this" as a bug is worse than no triage at all.

    The `[KEEP]` prefix is how the reporter says "do not change this". It is asked
    of the splitter, honored by the diagnoser, and — because a planner agent could
    drop it — recomputed locally and unioned into the returned protect list, which
    is the one output that must never shrink.
    """
    split_prompt, diagnose_prompt, consolidate_prompt = _agent_prompts()
    assert "[KEEP]" in split_prompt, "the splitter must be told to mark protect-this items [KEEP]"
    assert "[KEEP]" in diagnose_prompt, "the diagnoser must not treat a [KEEP] item as a defect"
    assert "[KEEP]" in consolidate_prompt, "the consolidator must emit the [KEEP] items as the protect list"
    assert "keeps = items.filter" in SRC and "'[KEEP]'" in SRC, "the protect list must also be derived in code"
    assert "protect = planned.concat(keeps" in SRC, "locally derived keeps must be unioned into the planner's list"


def test_every_result_carries_the_four_lists_plus_the_undiagnosed() -> None:
    """Every exit path must be usable to write /team dispatch briefs — and honest.

    A degraded run that returns fixNow but omits undiagnosed hands the caller a
    plausible-looking work list with items quietly missing from it.
    """
    exits = []
    for m in re.finditer(r"return \{", SRC):
        block = _brace_block(SRC, m.start())
        if "fixNow" in block:
            exits.append(block)
    assert len(exits) >= 3, f"expected the split-failure, plan-failure and success exits, found {len(exits)}"
    for block in exits:
        for key in ("fixNow", "decisionsNeeded", "questionsBack", "protect", "undiagnosed"):
            assert key in block, f"a return path omits {key}"


def test_decisions_needed_carries_the_recommendation_not_a_menu() -> None:
    """A triage returning "you could do A or B" has moved the work, not done it.

    `recommendation` is required by the schema so the agent cannot omit it, and the
    prompt explicitly forbids option menus — the schema alone would happily accept
    "A or B" stuffed into the field.
    """
    block = _brace_block(SRC, SRC.index("decisionsNeeded: {"))
    assert "recommendation:" in block, "decisionsNeeded entries must have a recommendation field"
    assert "required: ['question', 'recommendation', 'why']" in block, (
        "recommendation and its reasoning must be required, not optional"
    )
    assert "not a menu of options" in block, "the field description must rule out an option menu"
    consolidate_prompt = _agent_prompts()[2]
    assert "THE recommendation" in consolidate_prompt, "the prompt must demand one course of action"
    assert "Never an option menu" in consolidate_prompt, "the prompt must forbid option menus explicitly"
