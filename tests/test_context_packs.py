"""Context packs: size cap, staleness header, required sections, memory seed present.

Packs are discovered from the team yamls' context_pack fields, so this validates
whatever concrete teams ship in the package (none in the bare framework; the dev
team in dist/). The TEMPLATE.md files are not validated as live packs. Backticked
dir-pointer existence is checked only inside a real project checkout.
"""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
TEAMS = ROOT / ".claude" / "teams"
PACKS = TEAMS / "context-packs"
MEMORY = TEAMS / "memory"

MAX_PACK_CHARS = 12_000  # ~3k tokens — hard cap (design §Context packs)
DIR_POINTER = re.compile(r"`([A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.\-]+)*/)`")
IN_PROJECT = any((ROOT / d).is_dir() for d in ("src", "app", "lib", "packages", "server"))


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def team_ids() -> list[str]:
    skip = {"model-routing.yaml", "TEMPLATE.yaml"}
    return [p.stem for p in sorted(TEAMS.glob("*.yaml")) if p.name not in skip] or ["__none__"]


@pytest.mark.parametrize("team", team_ids())
def test_pack_structure(team: str) -> None:
    if team == "__none__":
        pytest.skip("no concrete team packs in this package (templates only)")
    pack_rel = load_yaml(TEAMS / f"{team}.yaml")["context_pack"]
    text = (TEAMS / pack_rel).read_text()
    assert len(text) <= MAX_PACK_CHARS, f"{team} pack over the 12k-char cap ({len(text)})"
    assert text.startswith(f"# Context Pack — {team}"), f"{team} pack missing the canonical header"
    assert "Staleness:" in text, "packs must carry a staleness header"
    for section in ("## Map", "## Trip-wires", "## Current state"):
        assert section in text, f"{team} pack missing section {section}"
    if IN_PROJECT:
        for pointer in DIR_POINTER.findall(text):
            assert (ROOT / pointer).is_dir(), f"{team} pack points at missing dir: {pointer}"


@pytest.mark.parametrize("team", team_ids())
def test_memory_seed(team: str) -> None:
    if team == "__none__":
        pytest.skip("no concrete team memory in this package (templates only)")
    text = (MEMORY / f"{team}.md").read_text()
    assert text.startswith(f"# Team lessons — {team}"), f"{team} memory missing the canonical seed heading"


def test_templates_present() -> None:
    assert (PACKS / "TEMPLATE.md").is_file(), "context-pack TEMPLATE.md must ship"
    assert (MEMORY / "TEMPLATE.md").is_file(), "memory TEMPLATE.md must ship"
