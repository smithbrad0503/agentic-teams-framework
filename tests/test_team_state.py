"""State schemas for board.json / events.jsonl. Runtime files are gitignored;
schema functions are exercised against embedded fixtures always, and against
real local state files when present (never required in CI)."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".claude" / "teams" / "state"

RUN_STATUSES = {
    "dispatched",
    "running",
    "pr-ready",
    "blocked",
    "review-stalemate",
    "needs-human",
    "ill-specified",
    "done",
}
EVENT_TYPES = {
    "dispatched",
    "pr_opened",
    "blocked",
    "contract_updated",
    "zone_conflict",
    "blocked_on",
    "done",
    # A run's end event carries its ACTUAL terminal status (v0.2.0+), so every
    # non-`pr-ready` run status is also a valid event type.
    "review-stalemate",
    "needs-human",
    "ill-specified",
}


def validate_board_entry(entry: dict) -> None:
    for key in ("id", "team", "ticket", "status", "ts"):
        assert key in entry, f"board entry missing {key}"
    assert entry["status"] in RUN_STATUSES, f"bad status {entry['status']}"


def validate_event(event: dict) -> None:
    for key in ("ts", "run", "team", "type"):
        assert key in event, f"event missing {key}"
    assert event["type"] in EVENT_TYPES, f"bad event type {event['type']}"


def test_fixture_board_entry() -> None:
    validate_board_entry(
        {
            "id": "backend-ticket-123-20260101T1030",
            "team": "backend",
            "ticket": "TICKET-123",
            "status": "dispatched",
            "branch": "ticket-123-backend",
            "pr": "",
            "worktree": "",
            "ts": "2026-01-01T10:30:00-05:00",
        }
    )


def test_fixture_event() -> None:
    validate_event(
        {
            "ts": "2026-01-01T11:02:00-05:00",
            "run": "backend-ticket-123-20260101T1030",
            "team": "backend",
            "type": "pr_opened",
            "ticket": "TICKET-123",
            "pr": "42",
        }
    )


def test_terminal_statuses_are_valid_event_types() -> None:
    """Every non-`pr-ready` terminal status is emitted verbatim as an event type."""
    terminal = {"blocked", "review-stalemate", "needs-human", "ill-specified"}
    assert terminal <= RUN_STATUSES
    assert terminal <= EVENT_TYPES


def test_runner_does_not_collapse_the_event_type() -> None:
    runner = (ROOT / ".claude" / "workflows" / "team-run.js").read_text()
    assert "'pr_opened' : 'blocked'" not in runner, (
        "the event type must not collapse four terminal statuses into 'blocked'"
    )
    assert "type: 'blocked'" not in runner, "the early-exit writer must not hardcode a type"
    assert "const eventType = status === 'pr-ready' ? 'pr_opened' : status" in runner
    assert "type: statusVal === 'pr-ready' ? 'pr_opened' : statusVal," in runner


def test_state_dir_gitignored() -> None:
    gitignore = (ROOT / ".gitignore").read_text()
    assert ".claude/teams/state/*" in gitignore
    assert "!.claude/teams/state/.gitkeep" in gitignore
    assert (STATE / ".gitkeep").is_file()


def test_real_state_files_if_present() -> None:
    board = STATE / "board.json"
    if board.is_file():
        for entry in json.loads(board.read_text())["runs"]:
            validate_board_entry(entry)
    events = STATE / "events.jsonl"
    if events.is_file():
        for line in events.read_text().splitlines():
            if line.strip():
                validate_event(json.loads(line))
