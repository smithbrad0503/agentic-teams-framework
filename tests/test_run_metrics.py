"""run_metrics.py: aggregation, degradation, price math, and reconciliation.

Fixture state trees are built in tmp_path — none of these tests depend on a real
project's telemetry existing. The gh CLI is stubbed everywhere; no test touches
the network.
"""

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import run_metrics  # noqa: E402


def stage(label, model, effort, tokens, ok=True, error=None):
    entry = {"label": label, "model": model, "effort": effort, "tokens": tokens, "ok": ok}
    if error:
        entry["error"] = error
    return entry


def run_record(run_id, **overrides):
    record = {
        "runId": run_id,
        "team": "dev",
        "ticket": "TKT-1",
        "size": "medium",
        "timestamp": "2026-01-01T10:30:00-05:00",
        "branch": "tkt-1-dev",
        "pr": "1",
        "status": "pr-ready",
        "rounds": 1,
        "history": [],
        "stages": [
            stage("decompose", "fable", "high", 1_000_000),
            stage("implement:1", "opus", "medium", 2_000_000),
            stage("test", "sonnet", "medium", 500_000),
            stage("review#1", "opus", "high", 500_000),
        ],
    }
    record.update(overrides)
    return record


def make_state(root: Path, runs, board=None) -> Path:
    state = root / ".claude" / "teams" / "state"
    (state / "runs").mkdir(parents=True)
    (state / ".gitkeep").write_text("")
    for record in runs:
        (state / "runs" / f"{record['runId']}.json").write_text(json.dumps(record))
    if board is not None:
        (state / "board.json").write_text(json.dumps({"runs": board}))
    return root


def board_entry(run_id, status="pr-ready", pr="1"):
    return {
        "id": run_id, "team": "dev", "ticket": "TKT-1", "status": status,
        "branch": "tkt-1-dev", "pr": pr, "worktree": "",
        "ts": "2026-01-01T10:30:00-05:00",
    }


def run(root: Path, *args) -> int:
    return run_metrics.main(["--project-root", str(root), *args])


def report_json(capsys, root: Path, *args) -> dict:
    assert run(root, "--json", *args) == 0
    return json.loads(capsys.readouterr().out)


# --- normal aggregation -----------------------------------------------------


def test_multi_run_aggregation(tmp_path, capsys):
    make_state(tmp_path, [
        run_record("a", pr="1"),
        run_record("b", pr="2", rounds=2, status="pr-ready"),
        run_record("c", pr="3", rounds=3, status="review-stalemate"),
        run_record("d", pr="", rounds=2, status="blocked",
                   stages=[stage("decompose", "fable", "high", 10_000, ok=False,
                                 error="agent threw")]),
    ])
    data = report_json(capsys, tmp_path)

    assert data["runs"] == 4
    census = {row["status"]: row["runs"] for row in data["census"]}
    assert census == {"pr-ready": 2, "review-stalemate": 1, "blocked": 1}
    assert data["pr_ready"] == 2
    assert data["runs_to_pr_rate"] == 50.0

    assert data["rounds"]["first_pass"] == 1
    assert data["rounds"]["known"] == 4
    assert data["rounds"]["first_pass_rate"] == 25.0
    assert {r["rounds"]: r["runs"] for r in data["rounds"]["distribution"]} == {1: 1, 2: 2, 3: 1}

    # 3 full runs at 4M tokens each + one 10k blocked run.
    assert data["tokens"]["total"] == 12_010_000
    assert data["tokens"]["median_per_run"] == 4_000_000
    assert data["tokens"]["mean_per_run"] == 12_010_000 / 4

    stages = {row["stage"]: row for row in data["stages"]}
    assert stages["implement"]["tokens"] == 6_000_000
    assert stages["implement"]["stages"] == 3
    assert stages["review"]["tokens"] == 1_500_000  # review#1 collapses to `review`
    assert stages["decompose"]["failures"] == 1

    routing = {(r["model"], r["effort"]): r for r in data["routing"]}
    assert routing[("opus", "medium")]["calls"] == 3
    assert routing[("opus", "medium")]["ok_rate"] == 100.0
    assert routing[("fable", "high")]["calls"] == 4
    assert routing[("fable", "high")]["ok"] == 3
    assert routing[("fable", "high")]["ok_rate"] == 75.0

    assert {r["stage"]: r["failures"] for r in data["stage_failures"]} == {"decompose": 1}


def test_text_output_is_readable(tmp_path, capsys):
    make_state(tmp_path, [run_record("a")])
    assert run(tmp_path) == 0
    out = capsys.readouterr().out
    assert "RUN CENSUS" in out
    assert "MODEL ROUTING EVIDENCE" in out
    assert "COST ESTIMATE" in out
    assert "runs-to-PR success rate: 1/1 = 100.0%" in out


# --- degradation ------------------------------------------------------------


def test_missing_state_dir_exits_1(tmp_path, capsys):
    assert run(tmp_path) == 1
    assert "no team state directory" in capsys.readouterr().err


def test_missing_runs_dir_exits_1(tmp_path, capsys):
    (tmp_path / ".claude" / "teams" / "state").mkdir(parents=True)
    assert run(tmp_path) == 1
    assert "no runs directory" in capsys.readouterr().err


def test_zero_runs_reports_cleanly(tmp_path, capsys):
    make_state(tmp_path, [])
    assert run(tmp_path) == 0
    out = capsys.readouterr().out
    assert "No runs recorded yet" in out
    assert "Traceback" not in out


def test_zero_runs_json_is_still_valid(tmp_path, capsys):
    make_state(tmp_path, [])
    data = report_json(capsys, tmp_path)
    assert data["runs"] == 0
    assert data["tokens"]["total"] == 0
    assert data["cost"]["low_usd"] == 0.0


def test_malformed_run_file_is_skipped_not_fatal(tmp_path, capsys):
    root = make_state(tmp_path, [run_record("good")])
    runs_dir = root / ".claude" / "teams" / "state" / "runs"
    (runs_dir / "truncated.json").write_text('{"runId": "bad", "stages": [')
    (runs_dir / "not-an-object.json").write_text("[1, 2, 3]")
    (runs_dir / "no-id.json").write_text('{"team": "dev"}')

    data = report_json(capsys, root)
    assert data["runs"] == 1
    assert len(data["skipped"]) == 3
    assert any("truncated.json" in note for note in data["skipped"])


def test_run_missing_optional_fields(tmp_path, capsys):
    """An early-exit `blocked` record carries no rounds/history and a bare stage."""
    make_state(tmp_path, [
        run_record("full"),
        {
            "runId": "sparse",
            "team": "dev",
            "ticket": "TKT-9",
            "status": "blocked",
            "stage": "decompose",
            "stages": [{"label": "decompose", "model": "fable", "effort": "high"}],
        },
    ])
    data = report_json(capsys, tmp_path)
    assert data["runs"] == 2
    assert data["rounds"]["missing"] == 1
    assert data["rounds"]["known"] == 1
    assert data["rounds"]["first_pass_rate"] == 100.0  # computed over known rounds only
    # A stage with no `tokens` and no `ok` counts as zero spend and a failure.
    assert data["tokens"]["total"] == 4_000_000
    assert {r["stage"]: r["failures"] for r in data["stage_failures"]} == {"decompose": 1}


def test_tolerates_unknown_extra_fields(tmp_path, capsys):
    """RUNNER_VERSION / verifiedAtHead are being added concurrently — ignore them."""
    make_state(tmp_path, [
        run_record("a", RUNNER_VERSION="2.1.0", verifiedAtHead=True),
    ])
    data = report_json(capsys, tmp_path)
    assert data["runs"] == 1


def test_unpriced_model_is_reported_not_silently_zeroed(tmp_path, capsys):
    make_state(tmp_path, [
        run_record("a", stages=[stage("implement:1", "some-new-model", "high", 1_000_000)]),
    ])
    data = report_json(capsys, tmp_path)
    assert data["cost"]["unpriced_models"] == ["some-new-model"]
    assert data["cost"]["unpriced_tokens"] == 1_000_000
    assert data["cost"]["low_usd"] == 0.0


# --- price math -------------------------------------------------------------


def test_blended_rate_endpoints():
    rate = {"input": 10.0, "output": 50.0}
    # All-input: 1M tokens * $10/M.
    assert run_metrics.blended(1_000_000, rate, 0.0) == 10.0
    # All-output: 1M tokens * $50/M.
    assert run_metrics.blended(1_000_000, rate, 1.0) == 50.0
    # 20% output: 0.8*10 + 0.2*50 = $18/M.
    assert run_metrics.blended(1_000_000, rate, 0.2) == 18.0


def test_cost_estimate_is_a_range_over_the_output_share(tmp_path, capsys):
    make_state(tmp_path, [
        run_record("a", stages=[stage("implement:1", "opus", "medium", 1_000_000)]),
    ])
    data = report_json(capsys, tmp_path)
    cost = data["cost"]
    low_share, high_share = cost["output_share_range"]
    assert [low_share, high_share] == list(run_metrics.OUTPUT_SHARE_RANGE)
    opus = run_metrics.PRICES["opus"]
    assert cost["low_usd"] == run_metrics.blended(1_000_000, opus, low_share)
    assert cost["high_usd"] == run_metrics.blended(1_000_000, opus, high_share)
    assert cost["low_usd"] < cost["high_usd"], "a range, not a fabricated point estimate"
    assert cost["low_usd_per_run"] == cost["low_usd"]  # single run


def test_prices_override_replaces_the_table(tmp_path, capsys):
    root = make_state(tmp_path, [
        run_record("a", stages=[stage("implement:1", "opus", "medium", 1_000_000)]),
    ])
    prices = tmp_path / "prices.json"
    prices.write_text(json.dumps({"opus": {"input": 1.0, "output": 1.0}}))
    data = report_json(capsys, root, "--prices", str(prices))
    # Flat $1/M in and out: any output share gives exactly $1.00.
    assert data["cost"]["low_usd"] == 1.0
    assert data["cost"]["high_usd"] == 1.0


def test_bad_prices_file_exits_1(tmp_path, capsys):
    root = make_state(tmp_path, [run_record("a")])
    prices = tmp_path / "prices.json"
    prices.write_text("{not json")
    assert run(root, "--prices", str(prices)) == 1
    assert "not valid JSON" in capsys.readouterr().err


# --- JSON shape -------------------------------------------------------------


def test_json_output_shape(tmp_path, capsys):
    make_state(tmp_path, [run_record("a")])
    data = report_json(capsys, tmp_path)
    for key in ("project_root", "runs", "skipped", "census", "pr_ready", "runs_to_pr_rate",
                "rounds", "tokens", "stages", "routing", "stage_failures", "cost"):
        assert key in data, f"missing top-level key {key}"
    assert set(data["census"][0]) == {"status", "runs", "pct"}
    assert set(data["rounds"]) == {"distribution", "known", "missing",
                                   "first_pass", "first_pass_rate"}
    assert set(data["tokens"]) == {"total", "mean_per_run", "median_per_run"}
    assert set(data["stages"][0]) == {"stage", "stages", "tokens", "pct_tokens",
                                      "mean_tokens", "failures"}
    assert set(data["routing"][0]) == {"model", "effort", "calls", "ok", "ok_rate",
                                       "tokens", "pct_tokens", "mean_tokens"}
    assert set(data["cost"]) == {"output_share_range", "per_model", "low_usd", "high_usd",
                                 "low_usd_per_run", "high_usd_per_run",
                                 "unpriced_models", "unpriced_tokens",
                                 # True when the unverified built-in price table was used;
                                 # consumers must not quote a figure computed from it.
                                 "builtin_prices"}
    assert data["cost"]["builtin_prices"] is True
    # Not requested, so absent.
    assert "gh" not in data and "reconcile" not in data


# --- GitHub cross-reference (stubbed; never a real network call) ------------


def stub_gh(monkeypatch, states, error=None):
    monkeypatch.setattr(run_metrics, "fetch_pr_states",
                        lambda root, numbers: (states, error))


def test_gh_summary_with_stubbed_states(tmp_path, capsys, monkeypatch):
    make_state(tmp_path, [
        run_record("a", pr="1"),
        run_record("b", pr="2"),
        run_record("c", pr="3"),
        run_record("d", pr=""),
    ])
    stub_gh(monkeypatch, {"1": "MERGED", "2": "MERGED", "3": "OPEN"})
    data = report_json(capsys, tmp_path, "--gh")
    gh = data["gh"]
    assert gh["prs_opened"] == 3
    assert gh["merged"] == 2
    assert gh["open"] == 1
    assert gh["closed_unmerged"] == 0
    assert gh["merge_rate"] == 100.0 * 2 / 3
    assert gh["low_usd_per_merged_pr"] == data["cost"]["low_usd"] / 2


def test_gh_unavailable_still_reports_offline_metrics(tmp_path, capsys, monkeypatch):
    make_state(tmp_path, [run_record("a")])
    stub_gh(monkeypatch, {}, error="gh CLI not found on PATH")
    assert run(tmp_path, "--gh") == 0
    out = capsys.readouterr().out
    assert "unavailable — gh CLI not found on PATH" in out
    assert "RUN CENSUS" in out, "offline metrics must still print"


def test_gh_is_off_by_default(tmp_path, capsys, monkeypatch):
    make_state(tmp_path, [run_record("a")])

    def explode(root, numbers):  # pragma: no cover - must never run
        raise AssertionError("gh must not be consulted without --gh/--reconcile")

    monkeypatch.setattr(run_metrics, "fetch_pr_states", explode)
    assert run(tmp_path) == 0


# --- reconciliation ---------------------------------------------------------


def test_reconcile_flags_board_entries_behind_merged_prs(tmp_path, capsys, monkeypatch):
    root = make_state(
        tmp_path,
        [run_record("a", pr="1"), run_record("b", pr="2")],
        board=[board_entry("a", status="pr-ready", pr="1"),
               board_entry("b", status="done", pr="2")],
    )
    stub_gh(monkeypatch, {"1": "MERGED", "2": "MERGED"})
    data = report_json(capsys, root, "--reconcile")
    findings = data["reconcile"]
    assert [f["kind"] for f in findings] == ["stale-board-status"]
    assert findings[0]["run"] == "a"


def test_reconcile_flags_board_claiming_done_on_an_open_pr(tmp_path, capsys, monkeypatch):
    root = make_state(tmp_path, [run_record("a", pr="1")],
                      board=[board_entry("a", status="done", pr="1")])
    stub_gh(monkeypatch, {"1": "OPEN"})
    data = report_json(capsys, root, "--reconcile")
    assert [f["kind"] for f in data["reconcile"]] == ["overstated-board-status"]


def test_reconcile_flags_missing_and_orphan_entries(tmp_path, capsys, monkeypatch):
    root = make_state(tmp_path, [run_record("a", pr="1")],
                      board=[board_entry("ghost", status="pr-ready", pr="9")])
    stub_gh(monkeypatch, {})
    data = report_json(capsys, root, "--reconcile")
    kinds = {f["kind"] for f in data["reconcile"]}
    assert kinds == {"missing-board-entry", "orphan-board-entry"}


def test_reconcile_flags_pr_mismatch(tmp_path, capsys, monkeypatch):
    root = make_state(tmp_path, [run_record("a", pr="1")],
                      board=[board_entry("a", status="pr-ready", pr="77")])
    stub_gh(monkeypatch, {})
    data = report_json(capsys, root, "--reconcile")
    assert any(f["kind"] == "pr-mismatch" for f in data["reconcile"])


def test_reconcile_accepts_human_curation_ahead_of_the_run_record(tmp_path, capsys, monkeypatch):
    """`done` on a `pr-ready` run is a human marking it finished — not a defect."""
    root = make_state(tmp_path, [run_record("a", pr="1")],
                      board=[board_entry("a", status="done", pr="1")])
    stub_gh(monkeypatch, {})  # no PR state to arbitrate with
    data = report_json(capsys, root, "--reconcile")
    assert data["reconcile"] == []


def test_reconcile_never_writes_board(tmp_path, capsys, monkeypatch):
    root = make_state(tmp_path, [run_record("a", pr="1")],
                      board=[board_entry("a", status="pr-ready", pr="1")])
    board_path = root / ".claude" / "teams" / "state" / "board.json"
    before = board_path.read_text()
    stub_gh(monkeypatch, {"1": "MERGED"})
    assert run(root, "--reconcile") == 0
    assert board_path.read_text() == before, "reconcile is report-only"
    assert "Nothing was changed" in capsys.readouterr().out


def test_reconcile_without_board_file(tmp_path, capsys, monkeypatch):
    root = make_state(tmp_path, [run_record("a", pr="1")])
    stub_gh(monkeypatch, {})
    data = report_json(capsys, root, "--reconcile")
    assert any("not present" in note for note in data["board_notes"])
    assert [f["kind"] for f in data["reconcile"]] == ["missing-board-entry"]


# --- stage label collapsing -------------------------------------------------


def test_stage_class_collapses_rounds_but_keeps_retries():
    assert run_metrics.stage_class("review#2") == "review"
    assert run_metrics.stage_class("implement:3") == "implement"
    assert run_metrics.stage_class("ci-fix#1") == "ci-fix"
    assert run_metrics.stage_class("decompose") == "decompose"
    # Retry spend stays visible — it is the evidence that a tier is too cheap.
    assert run_metrics.stage_class("decompose:retry") == "decompose:retry"
