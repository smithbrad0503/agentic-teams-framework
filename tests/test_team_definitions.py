"""Validate .claude/teams/ definitions: schema, roster agents exist, routing valid.

Team yamls are discovered dynamically (any *.yaml except model-routing.yaml and
TEMPLATE.yaml), so this suite works both in the bare framework package (no concrete
teams) and in an adopting project. Filesystem-path checks (ownership zones) run only
when this looks like a real project checkout, so the package's own CI stays green.
"""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
TEAMS = ROOT / ".claude" / "teams"
AGENTS = ROOT / ".claude" / "agents"

VALID_EFFORTS = {"low", "medium", "high", "xhigh", "max"}
STAGE_CLASSES = {
    "decompose",
    "implement",
    "write-tests",
    "docs-author",
    "mechanical",
    "review",
    "revision-fix",
    "librarian",
}
# `fallback` is not a stage class: it is the route a failed stage's retry escalates to.
# A team yaml may override it exactly like a stage class.
ROUTING_KEYS = STAGE_CLASSES | {"fallback"}

# "In project" = a conventional source dir exists next to .claude/. In the bare
# framework/dist package none of these exist, so ownership-zone existence is skipped.
IN_PROJECT = any((ROOT / d).is_dir() for d in ("src", "app", "lib", "packages", "server"))


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def discover_team_files() -> list[Path]:
    skip = {"model-routing.yaml", "TEMPLATE.yaml"}
    return sorted(p for p in TEAMS.glob("*.yaml") if p.name not in skip)


def team_ids() -> list[str]:
    return [p.stem for p in discover_team_files()] or ["__none__"]


def agent_file_exists(name: str) -> bool:
    return (AGENTS / f"{name}.md").is_file() or (AGENTS / "optional" / f"{name}.md").is_file()


def routing_file() -> dict:
    return load_yaml(TEAMS / "model-routing.yaml")


def routing_defaults() -> dict:
    return routing_file()["defaults"]


def assert_effort(stage: str, entry: dict) -> None:
    assert stage in ROUTING_KEYS, f"unknown routing key: {stage}"
    assert isinstance(entry.get("model"), str) and entry["model"], f"{stage}: model must be a non-empty string"
    assert entry.get("effort") in VALID_EFFORTS, f"{stage}: invalid effort {entry.get('effort')}"


@pytest.mark.parametrize("team", team_ids())
def test_team_yaml_schema(team: str) -> None:
    if team == "__none__":
        pytest.skip("no concrete team definitions in this package (templates only)")
    cfg = load_yaml(TEAMS / f"{team}.yaml")
    assert cfg["name"] == team, "name must equal the filename stem"
    assert cfg["type"] in {"delivery", "advisory"}
    assert cfg["output"] in {"pr", "document"}
    assert isinstance(cfg["mission"], str) and cfg["mission"]

    roster = cfg["roster"]
    assert agent_file_exists(roster["lead"]), f"roster lead references unknown agent: {roster['lead']}"
    for spec_agent in roster.get("specialists", []):
        assert agent_file_exists(spec_agent), f"roster references unknown agent: {spec_agent}"
    assert agent_file_exists(roster["test"]), f"roster test references unknown agent: {roster['test']}"

    assert cfg["ownership"], f"{team}: ownership zones required"
    for zone in cfg["ownership"]:
        assert isinstance(zone, str) and zone, f"{team}: ownership zone must be a non-empty string"
        if IN_PROJECT:
            assert (ROOT / zone).exists(), f"{team}: ownership zone does not exist: {zone}"

    assert (TEAMS / cfg["context_pack"]).is_file(), f"{team}: context pack missing"
    assert cfg["gates"] == ["code-review", "ci-green"]

    budgets = cfg["budget_defaults"]
    assert set(budgets) == {"small", "medium", "large"}
    assert budgets["small"] < budgets["medium"] < budgets["large"]

    defaults = routing_defaults()
    strongest = defaults["decompose"]["model"]  # the strongest tier by convention
    for stage, entry in (cfg.get("routing") or {}).items():
        assert_effort(stage, entry)
        if stage == "review":
            assert entry["model"] == strongest, "review gate must never be demoted below the strongest tier"


def test_model_routing_defaults() -> None:
    defaults = routing_defaults()
    assert set(defaults) == STAGE_CLASSES, "every stage class needs a global default"
    for stage, entry in defaults.items():
        assert_effort(stage, entry)
    # The gatekeeper is never cheaper than the planning stage.
    assert defaults["review"]["model"] == defaults["decompose"]["model"], (
        "review must route to the strongest tier (same as decompose)"
    )


def test_model_routing_declares_a_retry_fallback() -> None:
    """D5: the runner escalates a failed stage's retry to this route — it must exist,
    sit OUTSIDE `defaults` (it is not a stage class), and not be a cheap tier."""
    routing = routing_file()
    assert "fallback" not in routing["defaults"], "fallback is not a stage class"
    fallback = routing.get("fallback")
    assert isinstance(fallback, dict), "model-routing.yaml must declare a top-level fallback"
    assert_effort("fallback", fallback)
    assert fallback["model"] == routing["defaults"]["decompose"]["model"], (
        "the retry escalates UP: the fallback is the strongest tier, never a cheaper one"
    )
