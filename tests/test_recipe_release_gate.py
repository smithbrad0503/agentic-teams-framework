"""Structural tests for the `release-gate` recipe.

Workflow scripts cannot be executed by node or pytest, so these assert on the
source text. Each test pins a property that, if it broke, would produce a wrong
*release decision* rather than a merely ugly script.
"""

import re
from pathlib import Path

RECIPE = (
    Path(__file__).resolve().parents[1]
    / ".claude"
    / "workflows"
    / "recipes"
    / "release-gate.js"
)
TEXT = RECIPE.read_text()


def _block(header: str) -> str:
    """Return the source of a top-level `const <name> = ... => {` block.

    Blocks are closed by a `}` in column 0, which holds for every top-level
    arrow function in this file.
    """
    start = TEXT.index(header)
    end = TEXT.index("\n}\n", start)
    return TEXT[start:end]


def _verdict_expr() -> str:
    """The single expression that computes the three-valued verdict."""
    start = TEXT.index("const verdict =")
    return TEXT[start : TEXT.index("\n", start)]


def test_meta_is_a_literal_naming_its_own_file() -> None:
    """The dispatcher reads `meta` statically; a computed meta is unreadable.

    `meta.name` is how a recipe is invoked, so a drift between it and the
    filename stem makes the recipe silently unaddressable.
    """
    assert "export const meta = {" in TEXT, "missing meta export"
    assert "name: 'release-gate'" in TEXT, "meta.name must equal the filename stem"
    head = TEXT[: TEXT.index("// ---- args contract")]
    for computed in ("${", "args", "require(", "await "):
        assert computed not in head, f"meta must be a pure literal — found {computed!r}"
    assert "phases: [" in head, "meta must declare its phases"
    for title in ("Gates", "Smoke", "Verdict"):
        assert f"title: '{title}'" in head, f"meta.phases missing {title}"


def test_no_wall_clock_or_random_calls() -> None:
    """`Date.now`, `Math.random` and argless `new Date()` break Workflow resume.

    A resumed run replays the script; anything nondeterministic makes the replay
    diverge from the original run, so timestamps arrive via args instead.
    """
    for banned in ("Date.now", "Math.random", "new Date("):
        assert banned not in TEXT, f"{banned} breaks Workflow resume"
    assert "A.timestamp" in TEXT, "the timestamp must come from args, not from the clock"


def test_args_are_normalized_then_validated() -> None:
    """Args can arrive as a JSON string; an unguarded run then gates nothing.

    Without the guard, `A.staticChecks` on a string is undefined, the recipe
    runs zero gates and every gate is trivially green — a SHIP verdict for a
    build nobody checked.
    """
    assert "let A = args || {}" in TEXT, "missing args normalization"
    assert "typeof A === 'string'" in TEXT, "string args must be parsed"
    assert "JSON.parse(A)" in TEXT, "string args must be parsed"

    errors = re.findall(r"return \{ error: '([^']+)'", TEXT)
    assert len(errors) >= 4, f"expected an unparseable-args guard plus arg validation, got {errors}"
    for msg in errors:
        assert msg.startswith("release-gate: "), f"error message must name the recipe: {msg!r}"

    guards = TEXT[: TEXT.index("const GATE_SCHEMA")]
    assert "!Array.isArray(A.staticChecks) || !A.staticChecks.length" in guards, (
        "staticChecks must be validated non-empty — an empty gate list means every gate passes"
    )
    assert "A.artifactSmoke.requiredEvidence" in guards, (
        "a configured smoke stage with no required evidence proves nothing and must be rejected"
    )


def test_incomplete_exists_and_is_distinct_from_no_ship() -> None:
    """A gate that never ran must never be reported as a gate that failed.

    This is the whole point of the recipe. The source project maps a null agent
    result to `pass:false`, which is safe but conflates "we checked and it is
    broken" with "we never checked". NO-SHIP is a complete judgement; an un-run
    gate does not entitle the run to make one. INCOMPLETE must therefore be a
    first-class outcome that outranks NO-SHIP and never collapses into it — and
    obviously must never collapse into SHIP.
    """
    for verdict in ("'SHIP'", "'NO-SHIP'", "'INCOMPLETE'"):
        assert verdict in TEXT, f"missing verdict {verdict}"

    # A null gate agent becomes `unrun`, never `fail`.
    to_gate = _block("const toGate = (name, r) =>")
    assert "status: 'unrun'" in to_gate, "a null gate result must map to the unrun status"
    falsy_branch = to_gate[to_gate.index("    : {") :]
    assert "'fail'" not in falsy_branch, (
        "the null branch must not produce 'fail' — that is the conflation this recipe exists to fix"
    )

    expr = _verdict_expr()
    assert "unrun.length ? 'INCOMPLETE'" in expr, "un-run gates must yield INCOMPLETE"
    assert expr.index("unrun.length") < expr.index("failed.length"), (
        "INCOMPLETE must outrank NO-SHIP; testing failures first lets an un-run gate be "
        "reported as a failure, which invites 'fix that one thing and ship'"
    )

    # Both facts must survive to the caller regardless of which string won.
    tail = TEXT[TEXT.rindex("return {") :]
    for field in ("verdict,", "failed,", "unrun,"):
        assert field in tail, f"the result must carry {field!r} so neither fact is lost"


def test_exclusive_chain_runs_strictly_serially() -> None:
    """The chain guards a resource that file isolation cannot partition.

    A build lock, a device, an emulator or an exclusive test database is held
    machine-wide, so two links running concurrently corrupt each other's
    results. The chain must be a single `await`-per-link loop that is ONE
    element of the outer `parallel()` — never mapped into a `parallel()` over
    its own items, which would be exactly the concurrency it forbids.
    """
    chain = _block("const runExclusiveChain = async () => {")
    assert "for (const step of CHAIN)" in chain, "the chain must iterate its links in order"
    assert re.search(r"const r = await agent\(", chain), (
        "each link must be awaited before the next is dispatched"
    )
    assert "parallel(" not in chain, (
        "the chain body must never fan out — that breaks the exclusive-resource contract"
    )
    assert not re.search(r"parallel\(\s*(A\.exclusiveChain|CHAIN)", TEXT), (
        "the chain must not be handed to parallel() as a list of items"
    )

    # It is one element of the single fan-out, so independent work still runs alongside it.
    assert re.search(r"parallel\(\[\s*\n\s*runExclusiveChain,", TEXT), (
        "the chain must be the first element of the parallel() array"
    )
    assert "A.staticChecks.map(" in TEXT, "the independent static checks must fan out"


def test_required_evidence_items_are_reported_individually() -> None:
    """A smoke stage that returns "looks fine" proves nothing.

    Every caller-supplied assertion — a clean exit code, a specific log line, a
    nonzero record count — must be individually met or not met, and a
    requirement the agent silently skipped must not read as satisfied.
    """
    assert "requirement: { type: 'string'" in TEXT, "evidence entries must name their requirement"
    assert "met: { type: 'boolean' }" in TEXT, "each requirement needs its own met flag"
    assert "observed: { type: 'string'" in TEXT, "each requirement needs its own observation"

    assert "evidence = REQUIRED.map(" in TEXT, (
        "evidence must be reconciled against the caller's list, not taken from the agent verbatim"
    )
    assert "reported.find((e) => e.requirement === req)" in TEXT, (
        "each required item must be matched to its own report"
    )
    assert "reported: false" in TEXT and "reported: true" in TEXT, (
        "an unreported requirement must be distinguishable from a reported one"
    )
    assert "unreported.length ? 'unrun'" in TEXT, (
        "a skipped requirement is un-run coverage, not a passed gate and not a failed assertion"
    )
    assert "evidence NEVER CHECKED:" in TEXT, "skipped requirements must surface as issues"
    assert "REQUIRED.map((e, i) =>" in TEXT, (
        "the prompt must enumerate every required item so the agent cannot answer in aggregate"
    )


def test_ship_requires_every_gate_green() -> None:
    """SHIP is the only verdict that authorizes release, so it needs the strongest test.

    Deriving SHIP from `!failed.length` alone would ship on a run containing
    un-run or blocked gates. It must require that every gate positively passed,
    with NO-SHIP as the fallback for anything else.
    """
    expr = _verdict_expr()
    assert "gates.every((g) => g.status === 'pass') ? 'SHIP'" in expr, (
        "SHIP must require every gate to have positively passed"
    )
    assert expr.rstrip().endswith(": 'NO-SHIP'"), (
        "the fallback must be NO-SHIP so an unrecognized status can never ship"
    )
    assert TEXT.count("? 'SHIP'") == 1, (
        "SHIP must be produced in exactly one place — the computed verdict expression"
    )
    assert "shippable: verdict === 'SHIP'" in TEXT, (
        "the boolean handed to callers must be derived from the verdict, not computed twice"
    )
    # The prose agent must not be able to override the computed decision.
    assert "you may not change it" in TEXT, "the report agent must be told the verdict is fixed"
    assert "report: report ||" in TEXT, "a dead report agent must not change the verdict"
