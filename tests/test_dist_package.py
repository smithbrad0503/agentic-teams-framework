"""dist/dev-team-package/ must not drift from the library it was bundled from.

Covers: the runner and /team command are byte-identical copies of the library
originals, every bundled agent (except AGENTS.md) carries a PROJECT-CONTEXT
block, and the bundled org-memory seeds carry their canonical first lines.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / ".claude"
DIST = ROOT / "dist" / "dev-team-package" / ".claude"

BEGIN = "<!-- PROJECT-CONTEXT:BEGIN -->"
END = "<!-- PROJECT-CONTEXT:END -->"

ORG_MEMORY_HEADERS = {
    "decisions.md": "# Org decisions",
    "architecture.md": "# Org architecture facts",
    "lessons.md": "# Org lessons",
}


def test_dist_runner_matches_library() -> None:
    library_runner = (LIBRARY / "workflows" / "team-run.js").read_text()
    dist_runner = (DIST / "workflows" / "team-run.js").read_text()
    assert dist_runner == library_runner, (
        "dist/dev-team-package/.claude/workflows/team-run.js has drifted from "
        ".claude/workflows/team-run.js — copy the library file over the dist copy"
    )


def test_dist_team_command_matches_library() -> None:
    library_cmd = (LIBRARY / "commands" / "team.md").read_text()
    dist_cmd = (DIST / "commands" / "team.md").read_text()
    assert dist_cmd == library_cmd, (
        "dist/dev-team-package/.claude/commands/team.md has drifted from "
        ".claude/commands/team.md — copy the library file over the dist copy"
    )


def dist_agent_files() -> list[Path]:
    return [p for p in sorted((DIST / "agents").glob("*.md")) if p.name != "AGENTS.md"]


@pytest.mark.parametrize("path", dist_agent_files(), ids=lambda p: p.stem)
def test_dist_agent_has_one_project_context_block(path: Path) -> None:
    text = path.read_text()
    assert text.count(BEGIN) == 1, f"{path.name}: needs exactly one BEGIN marker"
    assert text.count(END) == 1, f"{path.name}: needs exactly one END marker"
    assert text.index(BEGIN) < text.index(END), f"{path.name}: markers out of order"


@pytest.mark.parametrize("fname,header", sorted(ORG_MEMORY_HEADERS.items()))
def test_dist_org_memory_seed_present(fname: str, header: str) -> None:
    path = DIST / "org-memory" / fname
    assert path.is_file(), f"{path}: missing from dist package"
    assert path.read_text().startswith(header), f"{path}: first line must be {header!r}"
