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
