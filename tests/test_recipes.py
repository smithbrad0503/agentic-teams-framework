"""Recipe workflow scripts: meta literal present, name matches stem, no wall-clock calls."""

from pathlib import Path

import pytest

RECIPES = Path(__file__).resolve().parents[1] / ".claude" / "workflows" / "recipes"
NAMES = [
    "health-check",
    "retro",
    "audit",
    "triage",
    "batch-author",
    "release-gate",
    "consistency-sweep",
    "first-run",
    "dependency-probe",
    "state-reconcile",
]


@pytest.mark.parametrize("name", NAMES)
def test_recipe_shape(name: str) -> None:
    text = (RECIPES / f"{name}.js").read_text()
    assert "export const meta" in text, f"{name}: missing meta export"
    assert f"name: '{name}'" in text, f"{name}: meta.name must equal the filename stem"
    for banned in ("Date.now", "Math.random", "new Date("):
        assert banned not in text, f"{name}: {banned} breaks Workflow resume"


@pytest.mark.parametrize("name", NAMES)
def test_recipe_returns_a_verdict(name: str) -> None:
    """Every recipe must return a `verdict`.

    Without a shared field, anything consuming recipe output — a status reader, a
    dashboard, a summary — needs per-recipe special-casing to answer "did this
    actually complete?". Four recipes independently invented four different
    spellings of that idea before this was pinned.
    """
    text = (RECIPES / f"{name}.js").read_text()
    assert "verdict" in text, f"{name}: must return a verdict field"


@pytest.mark.parametrize("name", NAMES)
def test_recipe_reserves_incomplete_for_agent_death(name: str) -> None:
    """INCOMPLETE is reserved across all recipes for "an agent died".

    Every recipe fans out to agents, and an agent can return nothing. Collapsing
    that into an ordinary pass/fail is the bug class this framework has now fixed
    three times: an audit that silently exonerated findings, a runner that reported
    a stale terminal status, and an event stream that flattened four outcomes into
    one. A result that could not be fully evaluated must say so in the one field a
    caller is guaranteed to read.
    """
    text = (RECIPES / f"{name}.js").read_text()
    assert "'INCOMPLETE'" in text, (
        f"{name}: must be able to report INCOMPLETE when an agent returns nothing — "
        "a degraded run that reads as a clean one is the failure mode this pins"
    )


def test_audit_distinguishes_dead_verifier_from_refutation() -> None:
    """A verifier that died must not silently exonerate a finding.

    `audit` refutes findings adversarially, so a falsy verdict means "not a real
    issue" and the finding is dropped. Collapsing a null agent result into that
    same falsy verdict fails OPEN: an audit that could not check a finding would
    report it as clean. The recipe must surface those separately.
    """
    text = (RECIPES / "audit.js").read_text()
    assert "'unverified'" in text, "audit must have an unverified verdict distinct from refuted"
    assert "unverified" in text.split("return {")[-1], (
        "audit must return the unverified findings — a count in the log alone still "
        "drops them from the caller's result"
    )
    assert "verified: !!(v && v.real)" not in text, (
        "the collapsed truthiness check is the bug: it makes a dead verifier "
        "indistinguishable from a successful refutation"
    )


@pytest.mark.parametrize("name,field", [("audit", "findings"), ("consistency-sweep", "violations")])
def test_dead_stage_one_is_caught_before_the_fan_out(name: str, field: str) -> None:
    """A stage-1 agent that returns null is NOT the same as one that throws.

    `agent()` returns null on failure — that is the COMMON case. Throwing is rare.
    But `((r && r.<field>) || [])` turns a null into an empty fan-out, which returns
    an empty array, which passes any `Array.isArray` recovery downstream. The item
    then reads CLEAN because nobody looked at it.

    Only stage 2, before the fan-out, can tell the two apart. This bug was fixed here
    three times: once for the dead verifier, once for the thrown stage, and once for
    this — the path that actually happens most often.
    """
    text = (RECIPES / f"{name}.js").read_text()
    assert f"!r || !Array.isArray(r.{field})" in text, (
        f"{name}: stage 2 must detect a null stage-1 result BEFORE fanning out"
    )
    assert f"((r && r.{field}) || [])" not in text, (
        f"{name}: the collapsing default is the bug — it makes a dead agent "
        "indistinguishable from a genuinely empty result"
    )
