"""Org-memory seeds: canonical headers, size caps, candidates section present."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OM = ROOT / ".claude" / "org-memory"
MAX_CHARS = 8_000
HEADERS = {
    "decisions.md": "# Org decisions",
    "architecture.md": "# Org architecture facts",
    "lessons.md": "# Org lessons",
}


@pytest.mark.parametrize("fname", sorted(HEADERS))
def test_seed_header_and_cap(fname: str) -> None:
    text = (OM / fname).read_text()
    assert text.splitlines()[0] == HEADERS[fname], f"{fname}: bad canonical header"
    assert len(text) <= MAX_CHARS, f"{fname}: over the {MAX_CHARS}-char cap"


def test_lessons_candidates_section() -> None:
    assert "## Candidates (pending curation)" in (OM / "lessons.md").read_text()
