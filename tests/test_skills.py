"""Plugin skills: frontmatter, plugin-root references, validator gate wired."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_skill(name: str) -> str:
    return (ROOT / "skills" / name / "SKILL.md").read_text()


def test_org_init_skill() -> None:
    text = read_skill("org-init")
    assert text.startswith("---")
    assert "name: org-init" in text
    assert "description:" in text
    assert "${CLAUDE_PLUGIN_ROOT}" in text
    assert "validate_org.py" in text
    assert "PROJECT-CONTEXT:BEGIN" in text
    assert "NEVER silently overwrite" in text


def test_recipe_new_skill() -> None:
    """The authoring skill must carry the invariants, not just describe the format.

    Workflow scripts cannot be executed by node or pytest, so nothing catches a bad
    recipe at author time except this skill and the structural tests it tells the
    author to write. Every rule pinned here was paid for by a real defect.
    """
    text = read_skill("recipe-new")
    assert text.startswith("---")
    assert "name: recipe-new" in text
    assert "description:" in text
    for banned in ("Date.now", "Math.random"):
        assert banned in text, f"must name {banned} as forbidden — it breaks Workflow resume"
    assert "INCOMPLETE" in text, "the reserved degraded verdict must be taught"
    assert "filter(Boolean)" in text, "must warn how a dead agent silently vanishes"
    assert "mutation" in text.lower(), (
        "must tell the author to mutation-check their own test — a test whose "
        "assertion cannot fail is worse than no test, and these tests are the only gate"
    )


def test_org_update_skill() -> None:
    text = read_skill("org-update")
    assert text.startswith("---")
    assert "name: org-update" in text
    assert "${CLAUDE_PLUGIN_ROOT}" in text
    assert "provenance" in text.lower()
    assert "validate_org.py" in text
    assert "Never" in text  # never-overwrite-silently doctrine present
