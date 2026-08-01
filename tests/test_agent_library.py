"""Every library agent carries yaml frontmatter and exactly one PROJECT-CONTEXT block."""

from pathlib import Path
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import validate_org  # noqa: E402

AGENTS = ROOT / ".claude" / "agents"
REGISTRY = AGENTS / "AGENTS.md"
BEGIN = "<!-- PROJECT-CONTEXT:BEGIN -->"
END = "<!-- PROJECT-CONTEXT:END -->"
# The generalist implementer seat. Staffed by /org-init when the repo scan finds no
# web/API/DB surface, which is the only roster answer for a game, a CLI, a library, a
# pipeline, or this framework's own repo.
GENERALIST = AGENTS / "software-engineer.md"


def agent_files() -> list[Path]:
    return [p for p in sorted(AGENTS.rglob("*.md")) if p.name != "AGENTS.md"]


def frontmatter(path: Path) -> dict:
    return yaml.safe_load(path.read_text().split("---", 2)[1])


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


@pytest.mark.parametrize("path", agent_files(), ids=lambda p: p.stem)
def test_agent_frontmatter_parses_and_names_its_own_file(path: Path) -> None:
    """Frontmatter must be parseable yaml whose `name` equals the filename stem.

    The harness invokes agents by filename, so a mismatch makes the agent unroutable.
    Parseability is not a given: descriptions are long unquoted scalars, and a single
    `key: value`-looking colon inside one silently turns the block into a yaml error.
    """
    front = frontmatter(path)
    assert isinstance(front, dict), f"{path.name}: frontmatter must be a yaml mapping"
    assert front.get("name") == path.stem, (
        f"{path.name}: frontmatter name is {front.get('name')!r} but the stem is {path.stem!r}"
    )
    description = front.get("description")
    assert isinstance(description, str) and description.strip(), (
        f"{path.name}: needs a non-empty description — the router matches requests against it"
    )


@pytest.mark.parametrize("path", agent_files(), ids=lambda p: p.stem)
def test_agent_is_registered_in_agents_md(path: Path) -> None:
    """An unregistered agent is one a team lead can route to but nothing documents."""
    assert path.stem in validate_org.registry_names(REGISTRY), (
        f"{path.name}: not listed in {REGISTRY.name} — add a roster line whose first token "
        f"is {path.stem!r}"
    )


def test_generalist_implementer_identity_exists() -> None:
    """The stack-agnostic seat must exist as a file.

    The parametrized tests above glob the directory, so deleting this agent would make
    them silently stop covering it rather than fail. This is the guard against that.
    """
    assert GENERALIST.is_file(), (
        f"{GENERALIST.name}: missing — without it /org-init has no honest roster answer for a "
        "project with no web/API/DB surface and falls back to a least-wrong web specialist"
    )


def test_generalist_stays_generic() -> None:
    """Named explicitly, so the sentinel is pinned even if the glob stops finding the file."""
    body = GENERALIST.read_text().split(BEGIN, 1)[1].split(END, 1)[0]
    assert "Filled by /org-init" in body, (
        f"{GENERALIST.name}: PROJECT-CONTEXT block no longer carries the unfilled sentinel"
    )


def test_generalist_description_routes_in_both_directions() -> None:
    """The description IS the routing logic, and it has to work both ways.

    A team lead picks an agentType by matching this text. If it only says what the agent
    is for, every stack with a real specialist misroutes here; if it only says what it is
    not for, nothing routes here at all. So it must name the no-specialist stacks it
    covers AND name the specialists to prefer when one genuinely fits.
    """
    description = frontmatter(GENERALIST)["description"]
    lowered = description.lower()
    for stack in ("cli", "librar", "pipeline", "embedded"):
        assert stack in lowered, (
            f"description must name the no-specialist stacks it covers — missing {stack!r}"
        )
    assert "do not" in lowered or "do NOT" in description, (
        "description must carry an explicit do-NOT-use-for clause, like every other identity"
    )
    for specialist in ("backend-expert", "frontend-expert", "api-expert", "database-expert"):
        assert specialist in description, (
            f"description must name {specialist} as the agent to prefer when it fits — an "
            "unnamed alternative cannot be routed to"
        )
    assert "specialist" in lowered, (
        "description must say to prefer the specific specialist when one genuinely fits"
    )
