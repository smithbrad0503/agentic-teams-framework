"""Recipe workflow scripts: meta literal present, name matches stem, no wall-clock calls."""

from pathlib import Path

import pytest

RECIPES = Path(__file__).resolve().parents[1] / ".claude" / "workflows" / "recipes"
NAMES = ["health-check", "retro", "audit"]


@pytest.mark.parametrize("name", NAMES)
def test_recipe_shape(name: str) -> None:
    text = (RECIPES / f"{name}.js").read_text()
    assert "export const meta" in text, f"{name}: missing meta export"
    assert f"name: '{name}'" in text, f"{name}: meta.name must equal the filename stem"
    for banned in ("Date.now", "Math.random", "new Date("):
        assert banned not in text, f"{name}: {banned} breaks Workflow resume"


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
