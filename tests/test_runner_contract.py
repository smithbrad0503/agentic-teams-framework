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


def test_retry_escalates_to_a_fallback_model() -> None:
    """D5: a retry that re-invokes the identical model cannot clear a model-level failure."""
    assert "const fallbackRoute = () =>" in RUNNER
    assert "cfg.routing.fallback" in RUNNER, "the fallback route must be read from config"
    block = RUNNER[RUNNER.index("const withRetry"):]
    block = block[: block.index("\n}\n")]
    assert "const fb = fallbackRoute()" in block, "the retry must consult the fallback route"
    assert "promptFn(true), retryOpts" in block, (
        "the retry must be invoked with the ESCALATED opts, not the opts that just failed"
    )
    assert "retrying on fallback model" in block, (
        "a retry on a different model than the primary must be logged"
    )


def test_null_stage_returns_record_a_reason() -> None:
    """D5: `ok:false` with no error text made a blocked run undiagnosable."""
    block = RUNNER[RUNNER.index("const call = async"):]
    block = block[: block.index("\n// The route a failed stage")]
    assert "no report returned by" in block, "a null return must record why it failed"
    assert ": res == null" in block, "the reason must cover null returns, not only throws"
    blocked_block = RUNNER[RUNNER.index("const blocked = async"):]
    blocked_block = blocked_block[: blocked_block.index("\n}\n")]
    assert "s.error" in blocked_block and "${stage}:retry" in blocked_block, (
        "the blocked note must surface the failing stage's recorded reason"
    )


def test_ci_schema_carries_an_infra_channel() -> None:
    """D3: an infrastructure failure needs a channel code can read, not free text."""
    schema = RUNNER[RUNNER.index("const CI_SCHEMA"):]
    schema = schema[: schema.index("\n// ---- Setup")]
    assert "infra: {" in schema and "type: 'boolean'" in schema
    assert "required: ['check', 'reason']," in schema, (
        "infra must stay OPTIONAL — an omitted flag reads as false and routes to the "
        "code fixer (the old behaviour), so an unfilled field never skips a real defect"
    )
    assert "infra: true when the failure has NO code cause" in RUNNER, (
        "the CI verification prompt must instruct the agent to set the flag"
    )


def test_infra_only_ci_red_reruns_without_spending_a_gate_round() -> None:
    """D3: bounded, round-free re-run path; the bound is what keeps the loop terminating."""
    assert "const MAX_CI_INFRA_RERUNS = A.maxCiInfraReruns || 2" in RUNNER
    assert "const allInfra = !!ci && failing.every((f) => f.infra === true)" in RUNNER, (
        "the re-run path fires only when EVERY failing check is infra"
    )
    assert "if (allInfra && ciInfraReruns < MAX_CI_INFRA_RERUNS) {" in RUNNER
    for refund in ("      gateSteps--", "      ciAttempts--"):
        assert refund in RUNNER, f"an infra re-run must refund {refund.strip()}"
    assert "`ci-rerun#${ciInfraReruns}`" in RUNNER
    assert "gh run rerun <run-id> --failed" in RUNNER, "the re-run stage must re-run jobs, not fix code"
    assert "ciAttempts, ciInfraReruns, gateSteps" in RUNNER, "the re-run count must reach telemetry"


def test_plan_schema_only_requires_feasible() -> None:
    """D9: {feasible:false, questions:[...]} must be a schema-VALID report."""
    schema = RUNNER[RUNNER.index("const PLAN_SCHEMA"):]
    schema = schema[: schema.index("const BUILD_SCHEMA")]
    assert "required: ['feasible'],\n}" in schema, (
        "requiring packages+testPlan makes the ill-specified escape hatch unreachable"
    )
    assert "When feasible=false, put your questions in questions and return packages=[]" in RUNNER, (
        "the conditional shape moves to the decompose prompt"
    )
    assert "decompose returned feasible=true without work packages or a test plan" in RUNNER, (
        "a feasible=true plan with no packages must block cleanly, not crash on .length"
    )


def test_size_is_not_advertised_as_a_budget_class() -> None:
    """D8a: `size` is recorded and drives nothing — the docs must not promise otherwise."""
    assert "budget class" not in RUNNER
    assert "TELEMETRY LABEL ONLY" in RUNNER
    cmd = (ROOT / ".claude" / "commands" / "team.md").read_text()
    assert "telemetry label only" in cmd, (
        "/team's usage must say what size actually is"
    )
    assert "It does not set a token budget, gate budget, or\nmodel effort" in cmd


def test_report_state_cost_is_recoverable() -> None:
    """D8b: the state-writer's own cost cannot be inside the record it writes."""
    assert "const tokensBeforeReport = DRY ? 0 : budget.spent()" in RUNNER
    assert "tokensBeforeReport, verifiedAtHead" in RUNNER, (
        "tokensBeforeReport must ride in telemetry so the writer's cost is recoverable"
    )
    assert "the regress does not terminate" in RUNNER, (
        "why the cost cannot simply be recorded in-file must stay documented"
    )


def test_ci_fix_re_review_fails_safe() -> None:
    """Only an explicit touchedSource === false skips the re-review."""
    assert "touchedSource" in RUNNER
    assert "ciFix.touchedSource === false" in RUNNER, (
        "the re-review skip must require an explicit false — a missing field, an "
        "unparsed report, or a null return has to route back through review"
    )
