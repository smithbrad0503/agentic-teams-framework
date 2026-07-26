#!/usr/bin/env python3
"""Validate a materialized agentic-org inside a project's .claude/ tree.

The /org-init skill runs this as its final hard gate; /org-update runs it after a
sync. Standalone: Python 3.10+ and PyYAML only.

    python3 scripts/validate_org.py --project-root /path/to/project

Exit 0 = valid. Exit 1 = errors, one per line on stderr.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

MAX_PACK_CHARS = 12_000
MAX_ORG_MEMORY_CHARS = 8_000
VALID_EFFORTS = {"low", "medium", "high", "xhigh", "max"}
STAGE_CLASSES = {
    "decompose", "implement", "write-tests", "docs-author",
    "mechanical", "review", "revision-fix", "librarian",
}
TIER_PLACEHOLDERS = {"strong", "mid", "cheap"}
REVIEW_EFFORTS = {"high", "xhigh", "max"}
ORG_MEMORY_HEADERS = {
    "decisions.md": "# Org decisions",
    "architecture.md": "# Org architecture facts",
    "lessons.md": "# Org lessons",
}
CANDIDATES_HEADING = "## Candidates (pending curation)"
PROVENANCE_RE = re.compile(r"agentic-org: v\d+\.\d+\.\d+ source=\S+")
CTX_BEGIN = "<!-- PROJECT-CONTEXT:BEGIN -->"
CTX_END = "<!-- PROJECT-CONTEXT:END -->"
PLACEHOLDER_SENTINEL = "Filled by /org-init"
# team-run.js hard-codes these agentTypes regardless of roster.
RUNNER_REQUIRED_AGENTS = ("code-reviewer", "debug-expert", "docs-author")
GITIGNORE_LINES = (".claude/teams/state/*", "!.claude/teams/state/.gitkeep")


def team_files(teams: Path) -> list[Path]:
    skip = {"model-routing.yaml", "TEMPLATE.yaml"}
    return [p for p in sorted(teams.glob("*.yaml")) if p.name not in skip]


def check_provenance(path: Path, errs: list[str]) -> None:
    head = "\n".join(path.read_text().splitlines()[:12])
    if not PROVENANCE_RE.search(head):
        errs.append(f"{path}: missing agentic-org provenance header in the first 12 lines")


def validate_team_yaml(path: Path, claude: Path) -> list[str]:
    errs: list[str] = []
    try:
        cfg = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        return [f"{path}: unparseable yaml ({exc})"]
    name = path.stem
    if cfg.get("name") != name:
        errs.append(f"{path}: name must equal the filename stem {name!r}")
    if cfg.get("type") not in {"delivery", "advisory"}:
        errs.append(f"{path}: type must be delivery|advisory")
    if cfg.get("output") not in {"pr", "document"}:
        errs.append(f"{path}: output must be pr|document")
    if not cfg.get("mission"):
        errs.append(f"{path}: mission required")
    roster = cfg.get("roster") or {}
    for role in ("lead", "test"):
        if not roster.get(role):
            errs.append(f"{path}: roster.{role} required")
    for agent_name in [roster.get("lead"), roster.get("test"), *(roster.get("specialists") or [])]:
        if agent_name and not (claude / "agents" / f"{agent_name}.md").is_file():
            errs.append(f"{path}: roster references missing agent {agent_name}")
    zones = cfg.get("ownership") or []
    if not zones:
        errs.append(f"{path}: ownership zones required")
    for zone in zones:
        if not isinstance(zone, str) or not zone.strip():
            errs.append(f"{path}: ownership zone must be a non-empty string: {zone!r}")
            continue
        if Path(zone).is_absolute():
            errs.append(f"{path}: ownership zone must be a relative path: {zone!r}")
            continue
        if ".." in Path(zone).parts:
            errs.append(f"{path}: ownership zone must not contain '..' segments: {zone!r}")
            continue
        if not (claude.parent / zone).exists():
            errs.append(f"{path}: ownership zone does not exist: {zone}")
    pack_rel = cfg.get("context_pack") or ""
    if not pack_rel or not (claude / "teams" / pack_rel).is_file():
        errs.append(f"{path}: context pack missing: {pack_rel!r}")
    if cfg.get("gates") != ["code-review", "ci-green"]:
        errs.append(f"{path}: gates must be [code-review, ci-green]")
    budgets = cfg.get("budget_defaults")
    if budgets is None:
        budgets = {}
    if not isinstance(budgets, dict):
        errs.append(f"{path}: budget_defaults must be a mapping of small/medium/large to numbers")
    else:
        budget_values_numeric = all(
            isinstance(budgets.get(k), (int, float)) and not isinstance(budgets.get(k), bool)
            for k in ("small", "medium", "large")
        )
        if set(budgets) != {"small", "medium", "large"} or not budget_values_numeric:
            errs.append(f"{path}: budget_defaults must define small, medium, large as numbers")
        elif not (budgets["small"] < budgets["medium"] < budgets["large"]):
            errs.append(f"{path}: budget_defaults must define small < medium < large")
    routing = cfg.get("routing")
    if routing is not None and not isinstance(routing, dict):
        errs.append(f"{path}: routing must be a mapping of stage -> {{model, effort}}")
    else:
        for stage, entry in (routing or {}).items():
            if stage not in STAGE_CLASSES:
                errs.append(f"{path}: unknown routing stage class {stage!r}")
            elif not isinstance(entry, dict) or not entry.get("model") or entry.get("effort") not in VALID_EFFORTS:
                errs.append(f"{path}: bad routing entry for {stage!r}")
            elif stage == "review" and entry.get("effort") not in REVIEW_EFFORTS:
                errs.append(f"{path}: review gate requires high/xhigh/max effort")
    return errs


def validate_routing(claude: Path) -> list[str]:
    path = claude / "teams" / "model-routing.yaml"
    if not path.is_file():
        return [f"{path}: missing"]
    errs: list[str] = []
    try:
        defaults = (yaml.safe_load(path.read_text()) or {}).get("defaults") or {}
    except yaml.YAMLError as exc:
        return [f"{path}: unparseable yaml ({exc})"]
    if set(defaults) != STAGE_CLASSES:
        errs.append(f"{path}: defaults must cover exactly the stage classes {sorted(STAGE_CLASSES)}")
    valid_entries: dict[str, dict] = {}
    for stage, entry in defaults.items():
        if not isinstance(entry, dict) or not entry.get("model") or entry.get("effort") not in VALID_EFFORTS:
            errs.append(f"{path}: bad entry for {stage!r}")
            continue
        valid_entries[stage] = entry
    if "review" in valid_entries and "decompose" in valid_entries:
        if valid_entries["review"]["model"] != valid_entries["decompose"]["model"]:
            errs.append(f"{path}: review must route to the strongest tier (same model as decompose)")
    if "review" in valid_entries and valid_entries["review"]["effort"] not in REVIEW_EFFORTS:
        errs.append(f"{path}: review gate requires high/xhigh/max effort")
    for stage, entry in valid_entries.items():
        if entry["model"] in TIER_PLACEHOLDERS:
            errs.append(f"{path}: {stage}: placeholder tier {entry['model']!r} not replaced with a real model identifier")
    return errs


def validate_pack(pack: Path, team: str) -> list[str]:
    errs: list[str] = []
    text = pack.read_text()
    if len(text) > MAX_PACK_CHARS:
        errs.append(f"{pack}: over the {MAX_PACK_CHARS}-char cap ({len(text)})")
    if not text.startswith(f"# Context Pack — {team}"):
        errs.append(f"{pack}: first line must be '# Context Pack — {team}'")
    if "Staleness:" not in text:
        errs.append(f"{pack}: missing staleness header")
    for section in ("## Map", "## Trip-wires", "## Current state"):
        if section not in text:
            errs.append(f"{pack}: missing section {section}")
    return errs


def validate_agent(path: Path) -> list[str]:
    errs: list[str] = []
    text = path.read_text()
    if not text.startswith("---") or "name:" not in text.split("---")[1]:
        errs.append(f"{path}: missing yaml frontmatter with a name field")
    if text.count(CTX_BEGIN) != 1 or text.count(CTX_END) != 1:
        errs.append(f"{path}: needs exactly one PROJECT-CONTEXT block")
        return errs
    body = text.split(CTX_BEGIN, 1)[1].split(CTX_END, 1)[0]
    if not body.strip():
        errs.append(f"{path}: PROJECT-CONTEXT block is empty — /org-init must fill it")
    if PLACEHOLDER_SENTINEL in body:
        errs.append(f"{path}: PROJECT-CONTEXT block still contains the library placeholder")
    return errs


def validate_org_memory(claude: Path) -> list[str]:
    errs: list[str] = []
    om = claude / "org-memory"
    for fname, header in ORG_MEMORY_HEADERS.items():
        path = om / fname
        if not path.is_file():
            errs.append(f"{path}: missing")
            continue
        text = path.read_text()
        if not text.startswith(header):
            errs.append(f"{path}: first line must be {header!r}")
        if len(text) > MAX_ORG_MEMORY_CHARS:
            errs.append(f"{path}: over the {MAX_ORG_MEMORY_CHARS}-char cap ({len(text)})")
        check_provenance(path, errs)
    lessons = om / "lessons.md"
    if lessons.is_file() and CANDIDATES_HEADING not in lessons.read_text():
        errs.append(f"{lessons}: missing the {CANDIDATES_HEADING!r} heading")
    return errs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a materialized agentic-org")
    parser.add_argument("--project-root", type=Path, default=Path("."))
    ns = parser.parse_args(argv)
    root = ns.project_root.resolve()
    claude = root / ".claude"
    errs: list[str] = []

    teams_dir = claude / "teams"
    teams = team_files(teams_dir) if teams_dir.is_dir() else []
    if not teams:
        errs.append(f"{teams_dir}: no team definitions found — run /org-init first")
    else:
        errs += validate_routing(claude)
        for tf in teams:
            errs += validate_team_yaml(tf, claude)
            check_provenance(tf, errs)
            try:
                pack_rel = (yaml.safe_load(tf.read_text()) or {}).get("context_pack") or ""
            except yaml.YAMLError:
                pack_rel = ""
            pack = teams_dir / pack_rel
            if pack_rel and pack.is_file():
                errs += validate_pack(pack, tf.stem)
                check_provenance(pack, errs)
            memory = teams_dir / "memory" / f"{tf.stem}.md"
            if not memory.is_file():
                errs.append(f"{memory}: missing team memory seed")
            elif not memory.read_text().startswith(f"# Team lessons — {tf.stem}"):
                errs.append(f"{memory}: first line must be '# Team lessons — {tf.stem}'")

        agents_dir = claude / "agents"
        for name in RUNNER_REQUIRED_AGENTS:
            if not (agents_dir / f"{name}.md").is_file():
                errs.append(f"{agents_dir}/{name}.md: missing — team-run.js hard-requires this agent")
        if agents_dir.is_dir():
            for agent_path in sorted(agents_dir.rglob("*.md")):
                if agent_path.name == "AGENTS.md":
                    continue
                lines = agent_path.read_text().splitlines()
                if not lines or lines[0].strip() != "---":
                    continue  # documentation (e.g. README.md), not an agent definition
                errs += validate_agent(agent_path)
                check_provenance(agent_path, errs)

        errs += validate_org_memory(claude)

        if not (claude / "workflows" / "team-run.js").is_file():
            errs.append(f"{claude}/workflows/team-run.js: missing — the runner must be materialized")
        if not (teams_dir / "state" / ".gitkeep").is_file():
            errs.append(f"{teams_dir}/state/.gitkeep: missing")
        gitignore = root / ".gitignore"
        ignore_text = gitignore.read_text() if gitignore.is_file() else ""
        for line in GITIGNORE_LINES:
            if line not in ignore_text:
                errs.append(f"{gitignore}: missing line {line!r}")

    if errs:
        for err in errs:
            print(err, file=sys.stderr)
        print(f"validate_org: {len(errs)} error(s)", file=sys.stderr)
        return 1
    print(f"validate_org: OK — {len(teams)} team(s) valid under {claude}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
