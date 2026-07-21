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
