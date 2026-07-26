"""Structural contract checks on team-run.js and the /team command copies.

The runner is a Workflow script (host globals, top-level return) — it cannot be
executed under node or pytest. These greps pin the load-bearing structures; the
dogfood dry-run exercises the real behavior.
"""

import re
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


def test_no_nondeterministic_time_or_randomness() -> None:
    """Workflow scripts must stay resumable — no wall-clock, no randomness."""
    for forbidden in ("Date.now(", "Math.random(", "new Date()"):
        assert forbidden not in RUNNER, f"{forbidden} breaks resume in a Workflow script"


def test_runner_version_reaches_telemetry() -> None:
    assert re.search(r"const RUNNER_VERSION = '\d+\.\d+\.\d+'", RUNNER), (
        "the runner must declare a semver RUNNER_VERSION"
    )
    assert RUNNER.count("runnerVersion: RUNNER_VERSION") == 2, (
        "RUNNER_VERSION must ride in BOTH the final telemetry object and the "
        "early-exit run record — otherwise a deployed copy cannot report what it is"
    )


def test_review_history_is_interpolated_into_the_prompt() -> None:
    """D1: `history` must reach the reviewer, not just telemetry."""
    assert "${priorReviewBlock()}" in RUNNER, (
        "prior-round findings must be rendered INTO the review prompt"
    )
    block = RUNNER[RUNNER.index("const priorReviewBlock"):]
    block = block[: block.index("\n}\n")]
    assert "history.filter" in block, "the block must be built from the run's own history"
    assert "resolvedPriorItems" in block, "round >=2 must re-check prior items explicitly"
    assert "nits, NOT mustFix" in block, (
        "first-time non-regression findings on a later round must be nits, not blockers"
    )


def test_review_schema_carries_optional_resolved_prior_items() -> None:
    schema = RUNNER[RUNNER.index("const REVIEW_SCHEMA"):]
    schema = schema[: schema.index("const CI_SCHEMA")]
    assert "resolvedPriorItems" in schema
    assert "required: ['verdict', 'mustFix']" in schema, (
        "resolvedPriorItems must stay OPTIONAL so an approving round-1 review is valid"
    )


def test_confirm_only_pass_exists() -> None:
    """D2: a bounded-out gate must verify its last fix against branch HEAD."""
    assert "'review:confirm'" in RUNNER and "'ci:confirm'" in RUNNER
    assert "CONFIRM-ONLY" in RUNNER
    assert "Do NOT open any new line of inquiry" in RUNNER
    assert "verifiedAtHead" in RUNNER
    assert "verifiedAtHead, stages, history" in RUNNER, (
        "verifiedAtHead must be reported in telemetry, not just computed"
    )


def test_confirm_only_review_cannot_promote_an_unverified_ci() -> None:
    assert "if (!clean && reviewOk && !ciOk && unverifiedCi) {" in RUNNER, (
        "a clearing confirm-only review buys exactly one CI check — it may never "
        "promote a run to pr-ready on its own"
    )
    assert "clean = reviewOk && ciOk" in RUNNER


def test_per_gate_budgets_are_read_from_config() -> None:
    """D4: review and CI carry independent, tunable budgets."""
    for line in (
        "const MAX_REVIEW_ROUNDS = A.maxReviewRounds || MAX_ROUNDS",
        "const MAX_CI_ATTEMPTS = A.maxCiAttempts || 3",
        "const MAX_GATE_ROUNDS = A.maxGateRounds || MAX_REVIEW_ROUNDS + MAX_CI_ATTEMPTS",
    ):
        assert line in RUNNER, f"missing tunable budget: {line}"
    assert "if (reviewRounds >= MAX_REVIEW_ROUNDS) break" in RUNNER
    assert "if (ciAttempts >= MAX_CI_ATTEMPTS) break" in RUNNER


def test_ci_fix_re_review_fails_safe() -> None:
    """Only an explicit touchedSource === false skips the re-review."""
    assert "touchedSource" in RUNNER
    assert "ciFix.touchedSource === false" in RUNNER, (
        "the re-review skip must require an explicit false — a missing field, an "
        "unparsed report, or a null return has to route back through review"
    )
