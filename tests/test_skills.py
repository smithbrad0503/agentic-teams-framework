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


def test_org_init_staffs_the_generalist_when_no_specialist_fits() -> None:
    """Roster selection must actually reach `software-engineer`, or it is never staffed.

    The library can carry a stack-agnostic implementer and still never use it: the
    delivery row of the roster table is what the wizard reads, and if that row only
    lists the four web-service specialists, a game/CLI/library repo still gets the
    least-wrong one. This pins the selection rule, not just the agent's existence.
    """
    text = read_skill("org-init")
    assert "software-engineer" in text, "the generalist must appear in roster selection"
    assert "no web/API/DB surface" in text, (
        "the selection rule must key on what the step-4 scan found, not on the stack's name"
    )


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
