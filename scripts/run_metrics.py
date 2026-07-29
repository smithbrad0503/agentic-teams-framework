#!/usr/bin/env python3
"""Read a project's .claude/teams/state/ and print the evidence table for it.

Every team-run writes a telemetry record to state/runs/<runId>.json and a board
entry to state/board.json. Nothing read those files until this script; the
`/model-eval` routing loop described in docs/design.md is doctrine with no
evidence feeding it. This is that reader.

    python3 scripts/run_metrics.py --project-root /path/to/project
    python3 scripts/run_metrics.py --project-root . --json
    python3 scripts/run_metrics.py --project-root . --gh --reconcile

Standalone: Python 3.10+ stdlib only. Exit 0 = report produced (including the
"no runs yet" case). Exit 1 = the state tree could not be read.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

# --- Price table ------------------------------------------------------------
# List prices in USD per million tokens, keyed by the model identifier the runner
# records in each stage record (model-routing.yaml's `model:` values).
#
# !! THESE ARE UNVERIFIED PLACEHOLDERS. !!
# They were seeded to make the arithmetic runnable, NOT read off a price sheet.
# Verify every rate against your provider's current published pricing before you
# quote a dollar figure to anyone — or override the whole table with
# --prices <file>. They are not negotiated rates, they ignore prompt caching and
# batch discounts, and they are the single largest source of error in the dollar
# figures below. The script prints a warning whenever the built-in table is used.
#
# More importantly: telemetry records only a TOTAL token count per stage
# (`budget.spent()` delta) with NO input/output split. Input and output are
# priced 5x apart, so a total alone cannot yield an exact cost. Everything
# downstream reports a RANGE — see OUTPUT_SHARE_RANGE.
PRICES: dict[str, dict[str, float]] = {
    "fable": {"input": 10.00, "output": 50.00},
    "opus": {"input": 5.00, "output": 25.00},
    "sonnet": {"input": 3.00, "output": 15.00},
    "haiku": {"input": 1.00, "output": 5.00},
}

# The plausible band for "what fraction of a stage's total tokens were output?".
# Agent stages are input-heavy — large context packs, repo reads, tool results —
# so the output share sits low. The band is deliberately wide: it is an honest
# statement of what the telemetry does not record, not a precision estimate.
# Narrowing it requires the runner to record input/output separately.
OUTPUT_SHARE_RANGE = (0.05, 0.30)

TERMINAL_STATUSES = (
    "pr-ready",
    "review-stalemate",
    "needs-human",
    "blocked",
    "ill-specified",
    "done",
    # Advisory runs (a team yaml's `output: document`). They open no PR, so they record an
    # empty `pr` and `branch` and are excluded from the runs-to-PR and merge-rate figures
    # by construction — those measure the delivery pipeline, not every run.
    "document-ready",
    "critique-stalemate",
)
# board.json statuses that assert a PR was merged / is still open.
BOARD_MERGED_STATUSES = {"done"}
BOARD_OPEN_STATUSES = {"pr-ready"}

_ROUND_SUFFIX = re.compile(r":\d+$")


def stage_class(label: str) -> str:
    """Collapse a per-stage label to its class.

    `review#2` -> `review`, `implement:3` -> `implement`. `decompose:retry` keeps
    its `:retry` suffix on purpose: retry spend is exactly the thing you want
    visible when deciding whether a tier is too cheap for a stage.
    """
    base = label.split("#", 1)[0]
    return _ROUND_SUFFIX.sub("", base)


# --- Loading ----------------------------------------------------------------


def load_prices(path: Path) -> tuple[dict, list[str]]:
    """Load a --prices override. Returns (table, errors)."""
    try:
        raw = json.loads(path.read_text())
    except OSError as exc:
        return {}, [f"{path}: cannot read price file ({exc.strerror or exc})"]
    except json.JSONDecodeError as exc:
        return {}, [f"{path}: not valid JSON ({exc})"]
    if not isinstance(raw, dict) or not raw:
        return {}, [f"{path}: expected a non-empty object of model -> {{input, output}}"]
    table: dict[str, dict[str, float]] = {}
    errs: list[str] = []
    for model, entry in raw.items():
        if not isinstance(entry, dict):
            errs.append(f"{path}: {model!r} must map to {{\"input\": n, \"output\": n}}")
            continue
        try:
            table[str(model)] = {
                "input": float(entry["input"]),
                "output": float(entry["output"]),
            }
        except (KeyError, TypeError, ValueError):
            errs.append(f"{path}: {model!r} needs numeric 'input' and 'output' rates")
    return table, errs


def load_runs(runs_dir: Path) -> tuple[list[dict], list[str]]:
    """Read every run record. Returns (runs, notes-about-files-we-skipped)."""
    runs: list[dict] = []
    skipped: list[str] = []
    for path in sorted(runs_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except OSError as exc:
            skipped.append(f"{path.name}: cannot read ({exc.strerror or exc})")
            continue
        except json.JSONDecodeError as exc:
            skipped.append(f"{path.name}: not valid JSON ({exc})")
            continue
        if not isinstance(data, dict):
            skipped.append(f"{path.name}: expected a JSON object, got {type(data).__name__}")
            continue
        if not data.get("runId"):
            # Tolerate it, but name it — a record with no id cannot be reconciled.
            skipped.append(f"{path.name}: no runId field")
            continue
        runs.append(data)
    return runs, skipped


def load_board(board_path: Path) -> tuple[list[dict], list[str]]:
    if not board_path.is_file():
        return [], [f"{board_path.name}: not present"]
    try:
        data = json.loads(board_path.read_text())
    except OSError as exc:
        return [], [f"{board_path.name}: cannot read ({exc.strerror or exc})"]
    except json.JSONDecodeError as exc:
        return [], [f"{board_path.name}: not valid JSON ({exc})"]
    entries = data.get("runs") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return [], [f"{board_path.name}: expected a top-level 'runs' list"]
    return [e for e in entries if isinstance(e, dict)], []


def stages_of(run: dict) -> list[dict]:
    stages = run.get("stages")
    if not isinstance(stages, list):
        return []
    return [s for s in stages if isinstance(s, dict)]


def tokens_of(stage: dict) -> int:
    value = stage.get("tokens", 0)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def run_tokens(run: dict) -> int:
    return sum(tokens_of(s) for s in stages_of(run))


# --- Metrics ----------------------------------------------------------------


def compute(runs: list[dict], prices: dict) -> dict:
    total = len(runs)
    census = Counter(str(r.get("status") or "unrecorded") for r in runs)

    rounds = Counter()
    rounds_missing = 0
    for run in runs:
        value = run.get("rounds")
        if isinstance(value, int) and not isinstance(value, bool):
            rounds[value] += 1
        else:
            rounds_missing += 1
    rounds_known = total - rounds_missing

    per_run = [run_tokens(r) for r in runs]
    tokens_total = sum(per_run)

    by_stage: dict[str, dict] = defaultdict(lambda: {"stages": 0, "tokens": 0, "failures": 0})
    routing: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"calls": 0, "ok": 0, "tokens": 0}
    )
    failures: Counter = Counter()
    for run in runs:
        for stage in stages_of(run):
            label = str(stage.get("label") or "unlabelled")
            cls = stage_class(label)
            tokens = tokens_of(stage)
            ok = bool(stage.get("ok"))
            entry = by_stage[cls]
            entry["stages"] += 1
            entry["tokens"] += tokens
            if not ok:
                entry["failures"] += 1
                failures[cls] += 1
            key = (str(stage.get("model") or "unrecorded"), str(stage.get("effort") or "unrecorded"))
            r = routing[key]
            r["calls"] += 1
            r["tokens"] += tokens
            r["ok"] += 1 if ok else 0

    tokens_by_model: Counter = Counter()
    for (model, _effort), r in routing.items():
        tokens_by_model[model] += r["tokens"]

    return {
        "runs": total,
        "census": [
            {"status": s, "runs": n, "pct": pct(n, total)}
            for s, n in sorted(census.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        "pr_ready": census.get("pr-ready", 0),
        "runs_to_pr_rate": pct(census.get("pr-ready", 0), total),
        "rounds": {
            "distribution": [
                {"rounds": k, "runs": v, "pct": pct(v, rounds_known)}
                for k, v in sorted(rounds.items())
            ],
            "known": rounds_known,
            "missing": rounds_missing,
            "first_pass": rounds.get(1, 0),
            "first_pass_rate": pct(rounds.get(1, 0), rounds_known),
        },
        "tokens": {
            "total": tokens_total,
            "mean_per_run": (tokens_total / total) if total else 0.0,
            "median_per_run": statistics.median(per_run) if per_run else 0.0,
        },
        "stages": [
            {
                "stage": name,
                "stages": e["stages"],
                "tokens": e["tokens"],
                "pct_tokens": pct(e["tokens"], tokens_total),
                "mean_tokens": (e["tokens"] / e["stages"]) if e["stages"] else 0.0,
                "failures": e["failures"],
            }
            for name, e in sorted(by_stage.items(), key=lambda kv: -kv[1]["tokens"])
        ],
        "routing": [
            {
                "model": model,
                "effort": effort,
                "calls": e["calls"],
                "ok": e["ok"],
                "ok_rate": pct(e["ok"], e["calls"]),
                "tokens": e["tokens"],
                "pct_tokens": pct(e["tokens"], tokens_total),
                "mean_tokens": (e["tokens"] / e["calls"]) if e["calls"] else 0.0,
            }
            for (model, effort), e in sorted(routing.items(), key=lambda kv: -kv[1]["tokens"])
        ],
        "stage_failures": [
            {"stage": s, "failures": n} for s, n in sorted(failures.items(), key=lambda kv: -kv[1])
        ],
        "cost": cost_estimate(tokens_by_model, total, prices),
    }


def pct(part: int, whole: int) -> float:
    return (100.0 * part / whole) if whole else 0.0


def cost_estimate(tokens_by_model: Counter, runs: int, prices: dict) -> dict:
    """Cost as a RANGE over plausible output shares. Never a single number.

    The telemetry has one total per stage. Input and output are priced 5x apart,
    so any single-number cost would be invented. We report the endpoints of
    OUTPUT_SHARE_RANGE and label the whole thing an estimate.
    """
    low_share, high_share = OUTPUT_SHARE_RANGE
    per_model = []
    low_total = high_total = 0.0
    unpriced_tokens = 0
    unpriced_models: list[str] = []
    for model, tokens in sorted(tokens_by_model.items(), key=lambda kv: -kv[1]):
        rate = prices.get(model)
        if not rate:
            unpriced_tokens += tokens
            unpriced_models.append(model)
            per_model.append(
                {"model": model, "tokens": tokens, "low_usd": None, "high_usd": None}
            )
            continue
        low = blended(tokens, rate, low_share)
        high = blended(tokens, rate, high_share)
        low_total += low
        high_total += high
        per_model.append(
            {"model": model, "tokens": tokens, "low_usd": low, "high_usd": high}
        )
    return {
        "output_share_range": [low_share, high_share],
        "per_model": per_model,
        "low_usd": low_total,
        "high_usd": high_total,
        "low_usd_per_run": (low_total / runs) if runs else 0.0,
        "high_usd_per_run": (high_total / runs) if runs else 0.0,
        "unpriced_models": unpriced_models,
        "unpriced_tokens": unpriced_tokens,
    }


def blended(tokens: int, rate: dict, output_share: float) -> float:
    per_million = rate["input"] * (1.0 - output_share) + rate["output"] * output_share
    return tokens * per_million / 1_000_000.0


# --- GitHub cross-reference (opt-in; never required) ------------------------


def fetch_pr_states(project_root: Path, numbers: list[str]) -> tuple[dict[str, str], str | None]:
    """Map PR number -> OPEN | MERGED | CLOSED via the gh CLI.

    Returns ({}, reason) when gh is missing, unauthenticated, or failing. The
    caller carries on with the offline metrics — this is a cross-reference, not
    a dependency, and the script must work with no network.
    """
    if not numbers:
        return {}, None
    if shutil.which("gh") is None:
        return {}, "gh CLI not found on PATH"
    limit = max(100, len(numbers) * 4)
    try:
        proc = subprocess.run(
            ["gh", "pr", "list", "--state", "all", "--limit", str(limit),
             "--json", "number,state"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=120,
        )
    except OSError as exc:
        return {}, f"could not run gh ({exc})"
    except subprocess.TimeoutExpired:
        return {}, "gh timed out after 120s"
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        return {}, f"gh failed: {detail[0] if detail else 'no detail'}"
    try:
        rows = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError as exc:
        return {}, f"gh returned unparseable JSON ({exc})"
    states = {}
    for row in rows:
        if isinstance(row, dict) and row.get("number") is not None:
            states[str(row["number"])] = str(row.get("state") or "UNKNOWN")
    return states, None


def pr_numbers(runs: list[dict]) -> list[str]:
    seen: list[str] = []
    for run in runs:
        pr = run.get("pr")
        if pr in (None, "", 0):
            continue
        value = str(pr)
        if value not in seen:
            seen.append(value)
    return seen


def gh_summary(runs: list[dict], states: dict[str, str], cost: dict) -> dict:
    numbers = pr_numbers(runs)
    known = [states[n] for n in numbers if n in states]
    merged = sum(1 for s in known if s == "MERGED")
    still_open = sum(1 for s in known if s == "OPEN")
    closed = sum(1 for s in known if s == "CLOSED")
    unknown = len(numbers) - len(known)
    low = cost.get("low_usd") or 0.0
    high = cost.get("high_usd") or 0.0
    return {
        "prs_opened": len(numbers),
        "merged": merged,
        "open": still_open,
        "closed_unmerged": closed,
        "unknown": unknown,
        "merge_rate": pct(merged, len(numbers)),
        "low_usd_per_merged_pr": (low / merged) if merged else None,
        "high_usd_per_merged_pr": (high / merged) if merged else None,
    }


# --- Reconciliation (report-only, deliberately) -----------------------------


def reconcile(runs: list[dict], board: list[dict], states: dict[str, str]) -> list[dict]:
    """Report board entries that disagree with the run records or with real PR state.

    REPORT ONLY — this never writes board.json. The board is a human-curated
    surface: `done` is a person's judgement that a run is finished, not a fact
    the runner produced. Silently rewriting state that a human curates is exactly
    the wrong default, and a script that "fixed" the board would destroy the
    signal it was meant to surface. Print the disagreements; let a person decide.
    """
    findings: list[dict] = []
    by_id = {str(e.get("id")): e for e in board if e.get("id")}
    run_by_id = {str(r.get("runId")): r for r in runs}

    for run_id, run in sorted(run_by_id.items()):
        entry = by_id.get(run_id)
        if entry is None:
            findings.append({
                "run": run_id, "kind": "missing-board-entry",
                "detail": "run record exists but the board has no entry for it",
            })
            continue
        run_pr = str(run.get("pr") or "")
        board_pr = str(entry.get("pr") or "")
        if run_pr != board_pr:
            findings.append({
                "run": run_id, "kind": "pr-mismatch",
                "detail": f"run records PR {run_pr or '(none)'}, board records {board_pr or '(none)'}",
            })
        board_status = str(entry.get("status") or "")
        run_status = str(run.get("status") or "")
        pr_state = states.get(board_pr or run_pr)
        if pr_state == "MERGED" and board_status not in BOARD_MERGED_STATUSES:
            findings.append({
                "run": run_id, "kind": "stale-board-status",
                "detail": f"PR #{board_pr or run_pr} is MERGED, board still says {board_status!r}",
            })
        elif pr_state in {"OPEN", "CLOSED"} and board_status in BOARD_MERGED_STATUSES:
            findings.append({
                "run": run_id, "kind": "overstated-board-status",
                "detail": f"board says {board_status!r} but PR #{board_pr or run_pr} is {pr_state}",
            })
        elif pr_state is None and board_status != run_status:
            # No PR state to arbitrate with. A board status ahead of the run
            # record is normal human curation (`done` after `pr-ready`), so only
            # flag it when the board is BEHIND or contradicts.
            if not (board_status in BOARD_MERGED_STATUSES and run_status in BOARD_OPEN_STATUSES):
                findings.append({
                    "run": run_id, "kind": "status-divergence",
                    "detail": f"run records {run_status!r}, board records {board_status!r}",
                })

    for entry_id in sorted(set(by_id) - set(run_by_id)):
        findings.append({
            "run": entry_id, "kind": "orphan-board-entry",
            "detail": "board entry has no matching run record under state/runs/",
        })
    return findings


# --- Rendering --------------------------------------------------------------


def n(value: float) -> str:
    return f"{round(value):,}"


def render(report: dict, out) -> None:
    w = lambda line="": print(line, file=out)  # noqa: E731

    w(f"Run metrics — {report['project_root']}")
    total = report["runs"]
    if report["skipped"]:
        w(f"Skipped {len(report['skipped'])} unreadable run file(s):")
        for note in report["skipped"]:
            w(f"  - {note}")
    if total == 0:
        w("No runs recorded yet — nothing to measure. Dispatch a team, then re-run this.")
        return
    w(f"Runs: {total}")
    w()

    w("RUN CENSUS")
    w(f"  {'status':<18}{'runs':>6}{'share':>9}")
    for row in report["census"]:
        w(f"  {row['status']:<18}{row['runs']:>6}{row['pct']:>8.1f}%")
    w(f"  runs-to-PR success rate: {report['pr_ready']}/{total} = {report['runs_to_pr_rate']:.1f}%")
    w()

    rounds = report["rounds"]
    w("GATE ROUNDS")
    w(f"  {'rounds':<18}{'runs':>6}{'share':>9}")
    for row in rounds["distribution"]:
        w(f"  {row['rounds']:<18}{row['runs']:>6}{row['pct']:>8.1f}%")
    if rounds["missing"]:
        w(f"  ({rounds['missing']} run(s) record no round count — excluded from the rate)")
    w(f"  first-pass gate rate: {rounds['first_pass']}/{rounds['known']} = "
      f"{rounds['first_pass_rate']:.1f}%")
    w()

    tok = report["tokens"]
    w("TOKENS")
    w(f"  total            {n(tok['total']):>14}")
    w(f"  mean per run     {n(tok['mean_per_run']):>14}")
    w(f"  median per run   {n(tok['median_per_run']):>14}")
    w()

    w("TOKENS BY STAGE CLASS")
    w(f"  {'stage':<18}{'calls':>7}{'tokens':>14}{'share':>9}{'mean':>12}{'fails':>7}")
    for row in report["stages"]:
        w(f"  {row['stage']:<18}{row['stages']:>7}{n(row['tokens']):>14}"
          f"{row['pct_tokens']:>8.1f}%{n(row['mean_tokens']):>12}{row['failures']:>7}")
    w()

    w("MODEL ROUTING EVIDENCE  (the input the demotion loop needs)")
    w(f"  {'model':<12}{'effort':<10}{'calls':>7}{'ok':>6}{'ok%':>8}"
      f"{'tokens':>14}{'share':>9}{'mean':>12}")
    for row in report["routing"]:
        w(f"  {row['model']:<12}{row['effort']:<10}{row['calls']:>7}{row['ok']:>6}"
          f"{row['ok_rate']:>7.1f}%{n(row['tokens']):>14}{row['pct_tokens']:>8.1f}%"
          f"{n(row['mean_tokens']):>12}")
    w("  Doctrine is start strong, demote on evidence. A (model, effort) row with a")
    w("  high ok% over many calls is a demotion candidate; the review gate is never one.")
    w()

    w("STAGE FAILURES")
    if report["stage_failures"]:
        for row in report["stage_failures"]:
            w(f"  {row['stage']:<18}{row['failures']:>6}")
    else:
        w("  none — every recorded stage returned ok")
    w()

    cost = report["cost"]
    low_share, high_share = cost["output_share_range"]
    w("COST ESTIMATE  (ESTIMATE — see the caveats below the table)")
    w(f"  {'model':<12}{'tokens':>14}{'low $':>12}{'high $':>12}")
    for row in cost["per_model"]:
        if row["low_usd"] is None:
            w(f"  {row['model']:<12}{n(row['tokens']):>14}{'unpriced':>12}{'unpriced':>12}")
        else:
            w(f"  {row['model']:<12}{n(row['tokens']):>14}"
              f"{row['low_usd']:>12,.2f}{row['high_usd']:>12,.2f}")
    w(f"  {'TOTAL':<12}{'':>14}{cost['low_usd']:>12,.2f}{cost['high_usd']:>12,.2f}")
    w(f"  {'per run':<12}{'':>14}{cost['low_usd_per_run']:>12,.2f}"
      f"{cost['high_usd_per_run']:>12,.2f}")
    w(f"  Range spans a {low_share:.0%}–{high_share:.0%} output-token share. Telemetry records")
    w("  only a TOTAL per stage with no input/output split, and input and output are")
    w("  priced 5x apart — a single-number cost would be invented, not measured.")
    if cost.get("builtin_prices"):
        w("  !! RATES ARE UNVERIFIED PLACEHOLDERS — the built-in table was seeded to make")
        w("  !! the arithmetic runnable, not read off a price sheet. Verify against your")
        w("  !! provider's published pricing (or pass --prices) before quoting any figure.")
    else:
        w("  Rates came from --prices; they still go stale as pricing changes.")
    if cost["unpriced_models"]:
        w(f"  Unpriced models excluded from the totals: {', '.join(cost['unpriced_models'])} "
          f"({n(cost['unpriced_tokens'])} tokens)")
    w()

    if report.get("gh_error"):
        w(f"GITHUB CROSS-REFERENCE: unavailable — {report['gh_error']}")
        w("  Offline metrics above are unaffected.")
        w()
    elif report.get("gh"):
        g = report["gh"]
        w("GITHUB CROSS-REFERENCE")
        w(f"  PRs opened        {g['prs_opened']:>6}")
        w(f"  merged            {g['merged']:>6}")
        w(f"  open              {g['open']:>6}")
        w(f"  closed unmerged   {g['closed_unmerged']:>6}")
        if g["unknown"]:
            w(f"  unknown to gh     {g['unknown']:>6}")
        w(f"  merge rate        {g['merge_rate']:>5.1f}%")
        if g["low_usd_per_merged_pr"] is not None:
            w(f"  est. cost per merged PR  ${g['low_usd_per_merged_pr']:,.2f}"
              f" – ${g['high_usd_per_merged_pr']:,.2f}")
        w()

    if report.get("reconcile") is not None:
        findings = report["reconcile"]
        w("BOARD RECONCILIATION  (report only — nothing was written)")
        for note in report.get("board_notes", []):
            w(f"  note: {note}")
        if not findings:
            w("  board agrees with the run records" +
              (" and with real PR state" if report.get("gh") else ""))
        else:
            w(f"  {len(findings)} disagreement(s):")
            for row in findings:
                w(f"  - [{row['kind']}] {row['run']}: {row['detail']}")
            w("  Nothing was changed. board.json is human-curated; correct it by hand.")
        w()


# --- Entry point ------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Report delivery, routing, and cost evidence from team-run telemetry",
    )
    parser.add_argument("--project-root", type=Path, default=Path("."))
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument("--prices", type=Path, help="JSON file overriding the built-in price table")
    parser.add_argument("--gh", action="store_true",
                        help="cross-reference PR merge state via the gh CLI (needs network)")
    parser.add_argument("--reconcile", action="store_true",
                        help="report board.json entries that disagree with reality (never writes)")
    ns = parser.parse_args(argv)

    root = ns.project_root.resolve()
    state = root / ".claude" / "teams" / "state"
    runs_dir = state / "runs"

    if not state.is_dir():
        print(f"{state}: no team state directory — has this project run /org-init and a team yet?",
              file=sys.stderr)
        return 1
    if not runs_dir.is_dir():
        print(f"{runs_dir}: no runs directory — no team-run has completed in this project yet.",
              file=sys.stderr)
        return 1

    prices = dict(PRICES)
    if ns.prices is not None:
        override, errs = load_prices(ns.prices)
        for err in errs:
            print(err, file=sys.stderr)
        if not override:
            return 1
        prices = override

    runs, skipped = load_runs(runs_dir)
    report = compute(runs, prices)
    report["project_root"] = str(root)
    report["skipped"] = skipped
    # Surfaced in both renderers: a dollar figure computed from the unverified
    # built-in table must never be quoted to anyone as if it were measured.
    report["cost"]["builtin_prices"] = ns.prices is None

    states: dict[str, str] = {}
    if ns.gh or ns.reconcile:
        states, gh_error = fetch_pr_states(root, pr_numbers(runs))
        if gh_error:
            report["gh_error"] = gh_error
        elif ns.gh:
            report["gh"] = gh_summary(runs, states, report["cost"])

    if ns.reconcile:
        board, board_notes = load_board(state / "board.json")
        report["board_notes"] = board_notes
        report["reconcile"] = reconcile(runs, board, states)

    if ns.json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        print()
    else:
        render(report, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
