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


@pytest.mark.parametrize("path", agent_files(), ids=lambda p: p.stem)
def test_library_agent_is_still_generic(path: Path) -> None:
    """Library agents must keep the unfilled sentinel.

    `/org-init` writes customized agents to `.claude/agents/` — the exact path the
    library occupies in THIS repo. Running the wizard here would fill these blocks
    with framework-specific context and ship project-specific agents to every
    adopter on the next release. The existing-org check does not catch it (it looks
    only for team yamls, and this repo has none), and the block-shape test above
    stays green either way, so the clobber would be silent. This is the guard.
    """
    body = path.read_text().split(BEGIN, 1)[1].split(END, 1)[0]
    assert "Filled by /org-init" in body, (
        f"{path.name}: PROJECT-CONTEXT block no longer carries the unfilled sentinel — "
        "was /org-init run against the library itself?"
    )
