#!/usr/bin/env python3
"""Validate a materialized agentic-org inside a project's .claude/ tree.

The /org-init skill runs this as its final hard gate; /org-update runs it after a
sync. Standalone: Python 3.10+ and PyYAML only.

    python3 scripts/validate_org.py --project-root /path/to/project

Exit 0 = valid. Exit 1 = errors, one per line on stderr.
Warnings print to stderr prefixed `warning:` and NEVER change the exit code — the
/org-init and /org-update gates key on the exit code alone, so a warning informs
without blocking a handover.

Adding an agent to a materialized org
-------------------------------------
Writing the markdown is the easy part; the wiring is what breaks. Do all six
steps. Each one maps to a check in this file, so the checklist and its
enforcement cannot drift apart.

1. Create `.claude/agents/<name>.md` with yaml frontmatter whose `name:` equals
   the filename stem `<name>`.                              -> validate_agent
2. Give it a non-empty `description:`. The harness router matches requests
   against that text; without it the agent is unroutable.   -> validate_agent
3. Fill the PROJECT-CONTEXT block with this project's specifics and remove the
   library's "Filled by /org-init" sentinel. (The library keeps the sentinel; a
   materialized org must not.)                              -> validate_agent
4. Put the provenance header inside the first 12 lines, so /org-update can
   diff the file against the library.                       -> check_provenance
5. Register it in `.claude/agents/AGENTS.md` — one roster line whose first
   token is the agent name. Unregistered means a team lead can route to an
   agentType nothing documents.                             -> registry_names
6. Staff it: add `<name>` to a `.claude/teams/<team>.yaml` roster. A roster
   naming a file that does not exist is an ERROR; a file on no roster is a
   WARNING (dead weight, not a broken org).                 -> validate_team_yaml
   Exception: code-reviewer / debug-expert / docs-author are required by the
   runner whether or not any roster names them.             -> RUNNER_REQUIRED_AGENTS
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
# `fallback` is not a stage class — it is the route a failed stage's retry escalates to.
# Optional (the runner has a conservative built-in default) but validated when present,
# both as the routing file's top-level key and as a per-team override.
ROUTING_KEYS = STAGE_CLASSES | {"fallback"}
TIER_PLACEHOLDERS = {"strong", "mid", "cheap"}
REVIEW_EFFORTS = {"high", "xhigh", "max"}
# A team's output mode decides which gates team-run.js actually runs, so it is what the
# declared `gates` list is validated against. `output` — not `type` — is the field the
# runner branches on; the two are required to agree so the yaml cannot lie about itself.
TYPE_FOR_OUTPUT = {"pr": "delivery", "document": "advisory"}
# Delivery: the runner opens a PR, so it can and does run both gates.
DELIVERY_GATES = ["code-review", "ci-green"]
# Advisory: the runner writes a document and never creates a branch or a PR. There is no
# PR for `ci-green` to watch, so requiring it declares a gate that can never be satisfied.
# What advisory DOES run is one adversarial critique gate by a non-author.
ADVISORY_GATES = ["critique"]
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
AGENTS_REGISTRY = "AGENTS.md"
# Leading decoration an AGENTS.md roster line may carry before the agent name:
# code-block indentation, list bullets, table pipes, quotes, emphasis, backticks.
ENTRY_DECORATION = " \t>-*+|#`\"'"
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
    output = cfg.get("output")
    if output not in TYPE_FOR_OUTPUT:
        errs.append(f"{path}: output must be pr|document")
    elif cfg.get("type") in {"delivery", "advisory"} and cfg["type"] != TYPE_FOR_OUTPUT[output]:
        errs.append(
            f"{path}: type {cfg['type']!r} and output {output!r} disagree — team-run.js branches on "
            f"output alone, so this team would run as {TYPE_FOR_OUTPUT[output]}. Set "
            f"'type: {TYPE_FOR_OUTPUT[output]}', or change output to the mode you meant"
        )
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
    # Gates are validated against what the team's output mode actually runs. `ci-green` is
    # a DELIVERY requirement: an advisory run never opens a PR, so there is no CI for that
    # gate to watch and declaring it promises a check nothing can ever perform.
    if output == "document":
        if cfg.get("gates") != ADVISORY_GATES:
            errs.append(
                f"{path}: an advisory team's gates must be [{', '.join(ADVISORY_GATES)}] — advisory "
                "runs one adversarial critique gate by a non-author and opens no PR, so 'ci-green' "
                "names a check it can never satisfy"
            )
    elif cfg.get("gates") != DELIVERY_GATES:
        errs.append(f"{path}: a delivery team's gates must be [{', '.join(DELIVERY_GATES)}]")
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
            if stage not in ROUTING_KEYS:
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
        routing = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        return [f"{path}: unparseable yaml ({exc})"]
    defaults = routing.get("defaults") or {}
    fallback = routing.get("fallback")
    if fallback is not None:
        if not isinstance(fallback, dict) or not fallback.get("model") or fallback.get("effort") not in VALID_EFFORTS:
            errs.append(f"{path}: fallback must be {{model, effort}} with effort in {sorted(VALID_EFFORTS)}")
        elif fallback["model"] in TIER_PLACEHOLDERS:
            errs.append(f"{path}: fallback: placeholder tier {fallback['model']!r} not replaced with a real model identifier")
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


def entry_name(line: str) -> str:
    """The agent name an AGENTS.md line documents, or '' if the line is prose.

    Deliberately format-agnostic: the shipped registry lists agents as indented
    lines inside a fenced roster block (`  backend-expert   Server-side ...`),
    but an org may reformat that as a bullet list, a definition list, or a
    markdown table. All four put the name first on the line, so that is what we
    key on — strip decoration off the left, take the first token, strip
    decoration and trailing punctuation off it.
    """
    stripped = line.strip().lstrip(ENTRY_DECORATION)
    if not stripped:
        return ""
    token = stripped.split()[0].strip(ENTRY_DECORATION + ",;:.()[]")
    if token.endswith(".md"):
        token = token[: -len(".md")]
    return token


def registry_names(registry: Path) -> set[str]:
    """Agent names documented in .claude/agents/AGENTS.md."""
    return {n for n in (entry_name(line) for line in registry.read_text().splitlines()) if n}


def validate_agent(path: Path, registered: set[str] | None = None) -> list[str]:
    """Check one agent file. `registered` = names found in AGENTS.md, or None to skip."""
    errs: list[str] = []
    text = path.read_text()
    stem = path.stem
    if not text.startswith("---") or "name:" not in text.split("---")[1]:
        errs.append(f"{path}: missing yaml frontmatter with a name field")
    else:
        try:
            front = yaml.safe_load(text.split("---", 2)[1])
        except yaml.YAMLError as exc:
            front = None
            errs.append(
                f"{path}: unparseable yaml frontmatter ({exc}) — fix the block between the first two '---' lines"
            )
        if isinstance(front, dict):
            name = front.get("name")
            if name != stem:
                errs.append(
                    f"{path}: frontmatter name is {name!r} but the filename stem is {stem!r} — "
                    f"the harness invokes agents by filename, so set 'name: {stem}' or rename the file to {name}.md"
                )
            description = front.get("description")
            if not isinstance(description, str) or not description.strip():
                errs.append(
                    f"{path}: frontmatter description is empty or missing — the router matches requests against it, "
                    "so this agent can never be selected; add a 'description:' line saying what to use it for and "
                    "what NOT to use it for"
                )
        elif front is not None:
            errs.append(f"{path}: frontmatter must be a yaml mapping with name and description keys")
    if registered is not None and stem not in registered:
        errs.append(
            f"{path}: not listed in {AGENTS_REGISTRY} — a team lead can route to an agentType nothing documents; "
            f"add this line to the roster block in .claude/agents/{AGENTS_REGISTRY}: "
            f"'  {stem}    <one-line remit — what it does, what it does not>'"
        )
    if text.count(CTX_BEGIN) != 1 or text.count(CTX_END) != 1:
        errs.append(f"{path}: needs exactly one PROJECT-CONTEXT block")
        return errs
    body = text.split(CTX_BEGIN, 1)[1].split(CTX_END, 1)[0]
    if not body.strip():
        errs.append(f"{path}: PROJECT-CONTEXT block is empty — /org-init must fill it")
    if PLACEHOLDER_SENTINEL in body:
        errs.append(
            f"{path}: PROJECT-CONTEXT block still contains the library placeholder "
            f"({PLACEHOLDER_SENTINEL!r}) — replace it with this project's stack, key paths, and commands"
        )
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
    warns: list[str] = []

    teams_dir = claude / "teams"
    teams = team_files(teams_dir) if teams_dir.is_dir() else []
    rostered: set[str] = set()
    if not teams:
        errs.append(f"{teams_dir}: no team definitions found — run /org-init first")
    else:
        errs += validate_routing(claude)
        for tf in teams:
            errs += validate_team_yaml(tf, claude)
            check_provenance(tf, errs)
            try:
                cfg = yaml.safe_load(tf.read_text()) or {}
            except yaml.YAMLError:
                cfg = {}
            if not isinstance(cfg, dict):
                cfg = {}
            pack_rel = cfg.get("context_pack") or ""
            roster = cfg.get("roster") or {}
            if isinstance(roster, dict):
                specialists = roster.get("specialists") or []
                members = [roster.get("lead"), roster.get("test"), *(specialists if isinstance(specialists, list) else [])]
                rostered |= {m for m in members if isinstance(m, str)}
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
            registry = agents_dir / AGENTS_REGISTRY
            registered: set[str] | None = None
            if registry.is_file():
                registered = registry_names(registry)
            else:
                errs.append(
                    f"{registry}: missing — the agent registry must be materialized alongside the agents, "
                    "or a team lead has no list of who it may route to; copy it from the library "
                    f"(${{CLAUDE_PLUGIN_ROOT}}/.claude/agents/{AGENTS_REGISTRY}) and add a provenance header"
                )
            for agent_path in sorted(agents_dir.rglob("*.md")):
                if agent_path.name == AGENTS_REGISTRY:
                    continue
                lines = agent_path.read_text().splitlines()
                if not lines or lines[0].strip() != "---":
                    continue  # documentation (e.g. README.md), not an agent definition
                errs += validate_agent(agent_path, registered)
                check_provenance(agent_path, errs)
                if agent_path.stem not in rostered and agent_path.stem not in RUNNER_REQUIRED_AGENTS:
                    warns.append(
                        f"{agent_path}: on no team roster — nothing can route to it. Either add "
                        f"{agent_path.stem!r} to a roster in .claude/teams/<team>.yaml or delete the file"
                    )

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

    # Warnings never affect the exit code — the /org-init and /org-update gates key on it alone.
    for warn in warns:
        print(f"warning: {warn}", file=sys.stderr)
    if warns:
        print(f"validate_org: {len(warns)} warning(s) — not fatal", file=sys.stderr)
    if errs:
        for err in errs:
            print(err, file=sys.stderr)
        print(f"validate_org: {len(errs)} error(s)", file=sys.stderr)
        return 1
    print(f"validate_org: OK — {len(teams)} team(s) valid under {claude}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
