"""Every library agent carries yaml frontmatter and exactly one PROJECT-CONTEXT block."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / ".claude" / "agents"
BEGIN = "<!-- PROJECT-CONTEXT:BEGIN -->"
END = "<!-- PROJECT-CONTEXT:END -->"


def agent_files() -> list[Path]:
    return [p for p in sorted(AGENTS.rglob("*.md")) if p.name != "AGENTS.md"]


@pytest.mark.parametrize("path", agent_files(), ids=lambda p: p.stem)
def test_agent_has_one_project_context_block(path: Path) -> None:
    text = path.read_text()
    assert text.startswith("---"), f"{path.name}: missing yaml frontmatter"
    assert text.count(BEGIN) == 1, f"{path.name}: needs exactly one BEGIN marker"
    assert text.count(END) == 1, f"{path.name}: needs exactly one END marker"
    assert text.index(BEGIN) < text.index(END), f"{path.name}: markers out of order"
