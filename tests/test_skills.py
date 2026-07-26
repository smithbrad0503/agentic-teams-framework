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


def test_org_update_skill() -> None:
    text = read_skill("org-update")
    assert text.startswith("---")
    assert "name: org-update" in text
    assert "${CLAUDE_PLUGIN_ROOT}" in text
    assert "provenance" in text.lower()
    assert "validate_org.py" in text
    assert "Never" in text  # never-overwrite-silently doctrine present
