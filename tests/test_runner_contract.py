"""Structural contract checks on team-run.js and the /team command copies.

The runner is a Workflow script (host globals, top-level return) — it cannot be
executed under node or pytest. These greps pin the load-bearing structures; the
dogfood dry-run exercises the real behavior.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = (ROOT / ".claude" / "workflows" / "team-run.js").read_text()


def test_core_invariant_intact() -> None:
    assert "It NEVER" in RUNNER, "core-invariant comment must survive edits"
    assert "DO NOT MERGE" in RUNNER


def test_org_memory_in_config_contract() -> None:
    assert "orgMemory" in RUNNER


def test_org_memory_injected_at_decompose_and_review() -> None:
    assert RUNNER.count("## Org memory (cross-team)") >= 2, (
        "org memory must be injected into both the decompose and review prompts"
    )


def test_org_lessons_pipeline() -> None:
    assert "orgLessons" in RUNNER
    assert "Candidates (pending curation)" in RUNNER


def test_team_command_resolves_org_memory() -> None:
    text = (ROOT / ".claude" / "commands" / "team.md").read_text()
    assert "org-memory" in text and "orgMemory" in text
