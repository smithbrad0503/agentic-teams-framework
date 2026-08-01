"""validate_org.py: a minimal valid materialized org passes; each defect class fails."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import validate_org  # noqa: E402

PROV = "<!-- agentic-org: v0.1.0 source={src} -->"


def agent_md(name: str) -> str:
    return (
        f"---\nname: {name}\ndescription: test agent for {name} duties\n---\n"
        + PROV.format(src=f".claude/agents/{name}.md")
        + f"\n# {name}\n\n## Project Context\n\n"
        "<!-- PROJECT-CONTEXT:BEGIN -->\nStack: python; tests via pytest; code in src/.\n"
        "<!-- PROJECT-CONTEXT:END -->\n"
    )


ROUTING = """# agentic-org: v0.1.0 source=.claude/teams/model-routing.yaml
fallback: { model: opus, effort: high }
defaults:
  decompose:    { model: opus, effort: high }
  implement:    { model: opus, effort: medium }
  write-tests:  { model: sonnet, effort: medium }
  docs-author:  { model: sonnet, effort: medium }
  mechanical:   { model: haiku, effort: low }
  review:       { model: opus, effort: high }
  revision-fix: { model: sonnet, effort: medium }
  librarian:    { model: haiku, effort: low }
"""

ALL_CHEAP_ROUTING = """# agentic-org: v0.1.0 source=.claude/teams/model-routing.yaml
defaults:
  decompose:    { model: haiku, effort: low }
  implement:    { model: haiku, effort: low }
  write-tests:  { model: haiku, effort: low }
  docs-author:  { model: haiku, effort: low }
  mechanical:   { model: haiku, effort: low }
  review:       { model: haiku, effort: low }
  revision-fix: { model: haiku, effort: low }
  librarian:    { model: haiku, effort: low }
"""

TEAM = """# agentic-org: v0.1.0 source=.claude/teams/TEMPLATE.yaml
name: dev
type: delivery
output: pr
mission: Ship the demo product's application code.
roster:
  lead: tech-lead
  specialists: [backend-expert]
  test: qa-tester
ownership:
  - src/
context_pack: context-packs/dev.md
gates: [code-review, ci-green]
budget_defaults: { small: 80000, medium: 200000, large: 500000 }
routing: {}
"""

PACK = (
    "# Context Pack — dev\n"
    + PROV.format(src=".claude/teams/context-packs/TEMPLATE.md")
    + "\n> Staleness: refreshed 2026-07-25 (org-init)\n\n"
    "## Map\n- App code: `src/` — the demo module\n\n"
    "## Trip-wires\n- none yet\n\n"
    "## Current state\n- fresh org — nothing in flight\n"
)

REGISTRY = (
    "# Agent Registry\n"
    + PROV.format(src=".claude/agents/AGENTS.md")
    + "\n\nMaterialized in this project: the roster below.\n\n"
    "## Roster\n\n"
    "```\n"
    "Lead\n"
    "  tech-lead        In-code architecture, ADRs, cross-module design\n"
    "\n"
    "Specialists\n"
    "  backend-expert   Server-side app code: routing, ORM, validation\n"
    "\n"
    "Test / gates\n"
    "  qa-tester        Test authoring, mocking, coverage gate\n"
    "  code-reviewer    Correctness/security review (REVIEW GATE)\n"
    "  debug-expert     Root-cause investigation across the stack\n"
    "  docs-author      Diff-driven repo-doc updates\n"
    "```\n"
)

ORG_MEMORY = {
    "decisions.md": "# Org decisions\n" + PROV.format(src=".claude/org-memory/decisions.md") + "\n- 2026-07-25 — python stack. Why: existing code.\n",
    "architecture.md": "# Org architecture facts\n" + PROV.format(src=".claude/org-memory/architecture.md") + "\n- src/: single module\n",
    "lessons.md": "# Org lessons\n" + PROV.format(src=".claude/org-memory/lessons.md") + "\n\n## Candidates (pending curation)\n",
}


def make_valid_org(root: Path) -> Path:
    claude = root / ".claude"
    (claude / "teams" / "context-packs").mkdir(parents=True)
    (claude / "teams" / "memory").mkdir()
    (claude / "teams" / "state").mkdir()
    (claude / "agents").mkdir()
    (claude / "org-memory").mkdir()
    (claude / "workflows").mkdir()
    (root / "src").mkdir()
    (claude / "teams" / "dev.yaml").write_text(TEAM)
    (claude / "teams" / "model-routing.yaml").write_text(ROUTING)
    (claude / "teams" / "context-packs" / "dev.md").write_text(PACK)
    (claude / "teams" / "memory" / "dev.md").write_text(
        "# Team lessons — dev\n" + PROV.format(src=".claude/teams/memory/TEMPLATE.md") + "\n"
    )
    (claude / "teams" / "state" / ".gitkeep").write_text("")
    for name in ("tech-lead", "backend-expert", "qa-tester", "code-reviewer", "debug-expert", "docs-author"):
        (claude / "agents" / f"{name}.md").write_text(agent_md(name))
    (claude / "agents" / "AGENTS.md").write_text(REGISTRY)
    for fname, text in ORG_MEMORY.items():
        (claude / "org-memory" / fname).write_text(text)
    (claude / "workflows" / "team-run.js").write_text("// runner copy placeholder for validation tests\n")
    (root / ".gitignore").write_text(".claude/teams/state/*\n!.claude/teams/state/.gitkeep\n")
    return root


def run(root: Path) -> int:
    return validate_org.main(["--project-root", str(root)])


def test_valid_org_passes(tmp_path: Path) -> None:
    assert run(make_valid_org(tmp_path)) == 0


def test_empty_project_fails(tmp_path: Path) -> None:
    assert run(tmp_path) == 1


def test_unfilled_project_context_fails(tmp_path: Path) -> None:
    root = make_valid_org(tmp_path)
    target = root / ".claude" / "agents" / "backend-expert.md"
    target.write_text(
        target.read_text().replace(
            "Stack: python; tests via pytest; code in src/.",
            "> Filled by /org-init with project-specific context.",
        )
    )
    assert run(root) == 1


def test_missing_provenance_fails(tmp_path: Path) -> None:
    root = make_valid_org(tmp_path)
    target = root / ".claude" / "teams" / "dev.yaml"
    target.write_text(target.read_text().replace(
        "# agentic-org: v0.1.0 source=.claude/teams/TEMPLATE.yaml\n", ""
    ))
    assert run(root) == 1


def test_unreplaced_tier_placeholder_fails(tmp_path: Path) -> None:
    root = make_valid_org(tmp_path)
    target = root / ".claude" / "teams" / "model-routing.yaml"
    target.write_text(target.read_text().replace("model: haiku", "model: cheap"))
    assert run(root) == 1


def test_demoted_review_gate_fails(tmp_path: Path) -> None:
    root = make_valid_org(tmp_path)
    target = root / ".claude" / "teams" / "model-routing.yaml"
    target.write_text(target.read_text().replace(
        "review:       { model: opus, effort: high }",
        "review:       { model: haiku, effort: low }",
    ))
    assert run(root) == 1


def test_malformed_retry_fallback_fails(tmp_path: Path) -> None:
    """The retry-escalation route is optional, but a present one must be well-formed."""
    root = make_valid_org(tmp_path)
    target = root / ".claude" / "teams" / "model-routing.yaml"
    target.write_text(target.read_text().replace(
        "fallback: { model: opus, effort: high }",
        "fallback: { model: opus, effort: turbo }",
    ))
    assert run(root) == 1


def test_placeholder_retry_fallback_fails(tmp_path: Path) -> None:
    root = make_valid_org(tmp_path)
    target = root / ".claude" / "teams" / "model-routing.yaml"
    target.write_text(target.read_text().replace(
        "fallback: { model: opus, effort: high }",
        "fallback: { model: strong, effort: high }",
    ))
    assert run(root) == 1


def test_routing_without_a_fallback_still_passes(tmp_path: Path) -> None:
    """An org materialized before v0.2.0 keeps validating — the runner has a default."""
    root = make_valid_org(tmp_path)
    target = root / ".claude" / "teams" / "model-routing.yaml"
    target.write_text(target.read_text().replace("fallback: { model: opus, effort: high }\n", ""))
    assert run(root) == 0


def test_team_fallback_override_is_accepted(tmp_path: Path) -> None:
    """`fallback` is a valid team-level routing key, not an unknown stage class."""
    root = make_valid_org(tmp_path)
    target = root / ".claude" / "teams" / "dev.yaml"
    target.write_text(target.read_text().replace(
        "routing: {}",
        "routing: { fallback: { model: opus, effort: high } }",
    ))
    assert run(root) == 0


def test_pack_over_cap_fails(tmp_path: Path) -> None:
    root = make_valid_org(tmp_path)
    pack = root / ".claude" / "teams" / "context-packs" / "dev.md"
    pack.write_text(pack.read_text() + "x" * 13_000)
    assert run(root) == 1


def test_missing_org_memory_fails(tmp_path: Path) -> None:
    root = make_valid_org(tmp_path)
    (root / ".claude" / "org-memory" / "lessons.md").unlink()
    assert run(root) == 1


def test_all_stages_cheap_including_review_fails(tmp_path: Path) -> None:
    """Every stage (including review) routed to the same cheap model with low effort.

    The relative review==decompose model check alone would pass this (both stages
    route to the same model), which is the false negative from Finding 1. The
    review-effort floor must catch it independently of model choice.
    """
    root = make_valid_org(tmp_path)
    target = root / ".claude" / "teams" / "model-routing.yaml"
    target.write_text(ALL_CHEAP_ROUTING)
    assert run(root) == 1


def test_team_review_override_low_effort_fails(tmp_path: Path) -> None:
    """A team yaml cannot demote the review gate's effort via a per-team override."""
    root = make_valid_org(tmp_path)
    target = root / ".claude" / "teams" / "dev.yaml"
    target.write_text(target.read_text().replace(
        "routing: {}",
        "routing: { review: { model: opus, effort: low } }",
    ))
    assert run(root) == 1


def test_budget_defaults_non_numeric_fails(tmp_path: Path) -> None:
    """A string budget value must produce a normal error, not a TypeError crash."""
    root = make_valid_org(tmp_path)
    target = root / ".claude" / "teams" / "dev.yaml"
    target.write_text(target.read_text().replace(
        "budget_defaults: { small: 80000, medium: 200000, large: 500000 }",
        "budget_defaults: { small: '80000', medium: 200000, large: 500000 }",
    ))
    assert run(root) == 1


def test_budget_defaults_list_fails(tmp_path: Path, capsys) -> None:
    """A list-valued budget_defaults must produce a normal error, not an AttributeError crash."""
    root = make_valid_org(tmp_path)
    target = root / ".claude" / "teams" / "dev.yaml"
    target.write_text(target.read_text().replace(
        "budget_defaults: { small: 80000, medium: 200000, large: 500000 }",
        "budget_defaults: [80000, 200000, 500000]",
    ))
    assert run(root) == 1
    err = capsys.readouterr().err
    assert "budget_defaults" in err


def test_budget_defaults_scalar_fails(tmp_path: Path, capsys) -> None:
    """A scalar-valued budget_defaults must produce a normal error, not an AttributeError crash."""
    root = make_valid_org(tmp_path)
    target = root / ".claude" / "teams" / "dev.yaml"
    target.write_text(target.read_text().replace(
        "budget_defaults: { small: 80000, medium: 200000, large: 500000 }",
        "budget_defaults: nope",
    ))
    assert run(root) == 1
    err = capsys.readouterr().err
    assert "budget_defaults" in err


def test_routing_as_list_fails(tmp_path: Path) -> None:
    """A team yaml with routing as a list (not a mapping) must not crash with AttributeError."""
    root = make_valid_org(tmp_path)
    target = root / ".claude" / "teams" / "dev.yaml"
    target.write_text(target.read_text().replace("routing: {}", "routing: [review, decompose]"))
    assert run(root) == 1


def test_ownership_zone_empty_string_fails(tmp_path: Path) -> None:
    root = make_valid_org(tmp_path)
    target = root / ".claude" / "teams" / "dev.yaml"
    target.write_text(target.read_text().replace("  - src/\n", "  - ''\n"))
    assert run(root) == 1


def test_ownership_zone_dotdot_fails(tmp_path: Path) -> None:
    root = make_valid_org(tmp_path)
    target = root / ".claude" / "teams" / "dev.yaml"
    target.write_text(target.read_text().replace("  - src/\n", "  - ../..\n"))
    assert run(root) == 1


def test_ownership_zone_absolute_path_fails(tmp_path: Path) -> None:
    root = make_valid_org(tmp_path)
    target = root / ".claude" / "teams" / "dev.yaml"
    target.write_text(target.read_text().replace("  - src/\n", "  - /etc\n"))
    assert run(root) == 1


def test_agents_dir_readme_without_frontmatter_passes(tmp_path: Path) -> None:
    """Non-agent documentation (no YAML frontmatter) in .claude/agents/ is skipped, not rejected."""
    root = make_valid_org(tmp_path)
    (root / ".claude" / "agents" / "README.md").write_text(
        "# Agents\n\nSee individual files in this directory for role definitions.\n"
    )
    assert run(root) == 0


# --- adding an agent: the wiring checklist in validate_org.py's docstring ---


def add_agent(root: Path, name: str, *, register: bool = True, roster: bool = True,
              body: str | None = None) -> Path:
    """Wire a new agent in the way the checklist prescribes; skip steps to break it."""
    path = root / ".claude" / "agents" / f"{name}.md"
    path.write_text(agent_md(name) if body is None else body)
    if register:
        registry = root / ".claude" / "agents" / "AGENTS.md"
        registry.write_text(registry.read_text().replace(
            "Specialists\n",
            f"Specialists\n  {name}   specialist wired in by this test\n",
        ))
    if roster:
        team = root / ".claude" / "teams" / "dev.yaml"
        team.write_text(team.read_text().replace(
            "specialists: [backend-expert]", f"specialists: [backend-expert, {name}]"
        ))
    return path


def test_fully_wired_agent_passes(tmp_path: Path, capsys) -> None:
    """File + matching name + description + filled context + registry line + roster seat."""
    root = make_valid_org(tmp_path)
    add_agent(root, "sre")
    assert run(root) == 0
    assert "warning:" not in capsys.readouterr().err


def test_agent_name_not_matching_filename_stem_fails(tmp_path: Path, capsys) -> None:
    """The harness invokes by filename; a divergent frontmatter name makes it unreachable."""
    root = make_valid_org(tmp_path)
    add_agent(root, "sre", body=agent_md("sre").replace("name: sre", "name: site-reliability"))
    assert run(root) == 1
    err = capsys.readouterr().err
    assert "sre.md" in err and "filename stem" in err


def test_materialized_agent_keeping_the_unfilled_sentinel_fails(tmp_path: Path, capsys) -> None:
    """Opposite polarity to test_agent_library.py: the LIBRARY keeps this sentinel, an org must not."""
    root = make_valid_org(tmp_path)
    add_agent(root, "sre", body=agent_md("sre").replace(
        "Stack: python; tests via pytest; code in src/.",
        "> Filled by /org-init with project-specific context.",
    ))
    assert run(root) == 1
    assert "library placeholder" in capsys.readouterr().err


def test_agent_missing_from_registry_fails(tmp_path: Path, capsys) -> None:
    root = make_valid_org(tmp_path)
    add_agent(root, "sre", register=False)
    assert run(root) == 1
    err = capsys.readouterr().err
    assert "AGENTS.md" in err and "sre" in err


def test_missing_registry_file_fails(tmp_path: Path, capsys) -> None:
    """No AGENTS.md at all is one clear error, not one per agent."""
    root = make_valid_org(tmp_path)
    (root / ".claude" / "agents" / "AGENTS.md").unlink()
    assert run(root) == 1
    err = capsys.readouterr().err
    assert "AGENTS.md: missing" in err
    assert "not listed in AGENTS.md" not in err


def test_unrostered_agent_warns_but_still_passes(tmp_path: Path, capsys) -> None:
    """Dead weight, not a broken org: it must warn on stderr and leave the exit code at 0."""
    root = make_valid_org(tmp_path)
    add_agent(root, "sre", roster=False)
    assert run(root) == 0
    err = capsys.readouterr().err
    assert "warning:" in err and "sre.md" in err and "on no team roster" in err


def test_runner_required_agents_are_never_reported_as_unrostered(tmp_path: Path, capsys) -> None:
    """code-reviewer/debug-expert/docs-author are staffed by the runner, not by a roster."""
    root = make_valid_org(tmp_path)
    assert run(root) == 0
    assert "warning:" not in capsys.readouterr().err


def test_missing_runner_required_agent_fails(tmp_path: Path, capsys) -> None:
    root = make_valid_org(tmp_path)
    (root / ".claude" / "agents" / "debug-expert.md").unlink()
    assert run(root) == 1
    assert "debug-expert.md: missing" in capsys.readouterr().err


def test_agent_without_description_fails(tmp_path: Path, capsys) -> None:
    """The router matches on description; no description means the agent is unroutable."""
    root = make_valid_org(tmp_path)
    add_agent(root, "sre", body=agent_md("sre").replace("description: test agent for sre duties\n", ""))
    assert run(root) == 1
    assert "description is empty or missing" in capsys.readouterr().err


def test_agent_with_blank_description_fails(tmp_path: Path, capsys) -> None:
    root = make_valid_org(tmp_path)
    add_agent(root, "sre", body=agent_md("sre").replace(
        "description: test agent for sre duties", "description: '   '"
    ))
    assert run(root) == 1
    assert "description is empty or missing" in capsys.readouterr().err


def test_roster_naming_a_nonexistent_agent_fails(tmp_path: Path, capsys) -> None:
    """Pre-existing check, kept: a roster seat with no file behind it is an error."""
    root = make_valid_org(tmp_path)
    team = root / ".claude" / "teams" / "dev.yaml"
    team.write_text(team.read_text().replace(
        "specialists: [backend-expert]", "specialists: [backend-expert, ghost-expert]"
    ))
    assert run(root) == 1
    assert "roster references missing agent ghost-expert" in capsys.readouterr().err


def test_registry_entries_are_read_from_bullet_and_table_formats(tmp_path: Path) -> None:
    """AGENTS.md format is not assumed: name-first lines register in any common layout."""
    root = make_valid_org(tmp_path)
    add_agent(root, "sre", register=False)
    registry = root / ".claude" / "agents" / "AGENTS.md"
    registry.write_text(
        registry.read_text()
        + "\n- `sre` — incident response, monitoring, DR\n"
        + "\n| ux-designer | flows, wireframes |\n"
    )
    assert run(root) == 0
    assert validate_org.entry_name("| ux-designer | flows, wireframes |") == "ux-designer"
    assert validate_org.entry_name("- **sre** — incident response") == "sre"
    assert validate_org.entry_name("  sre.md  incident response") == "sre"


# --- project-owned agents: generated by /org-init, no upstream, never synced ---

PROJECT_OWNED = (
    "<!-- agentic-org: project-owned kind=integration generated-by=/org-init v0.1.0 — "
    "no upstream library file; /org-update never syncs or overwrites it -->"
)


def project_owned_agent_md(name: str) -> str:
    """An agent /org-init GENERATED from repo evidence: identical wiring, no `source=`."""
    return agent_md(name).replace(PROV.format(src=f".claude/agents/{name}.md"), PROJECT_OWNED)


def test_project_owned_agent_passes(tmp_path: Path, capsys) -> None:
    """The generated-integration case the library can never curate must validate."""
    root = make_valid_org(tmp_path)
    add_agent(root, "stripe-expert", body=project_owned_agent_md("stripe-expert"))
    assert run(root) == 0
    assert "warning:" not in capsys.readouterr().err


def test_agent_with_no_provenance_header_at_all_still_fails(tmp_path: Path, capsys) -> None:
    """The marker is explicit ON PURPOSE: absence must never be read as project-owned.

    An omitted header is indistinguishable from a forgotten one, so exempting
    headerless agents would silently swallow the exact bug this check exists to catch.
    """
    root = make_valid_org(tmp_path)
    add_agent(root, "stripe-expert", body=agent_md("stripe-expert").replace(
        PROV.format(src=".claude/agents/stripe-expert.md") + "\n", ""
    ))
    assert run(root) == 1
    assert "missing agentic-org provenance header" in capsys.readouterr().err


def test_malformed_library_provenance_on_an_agent_still_fails(tmp_path: Path, capsys) -> None:
    """Accepting a second kind must not weaken the first: a broken `v<semver> source=` is
    still an error, not a file that quietly slips through as project-owned."""
    root = make_valid_org(tmp_path)
    add_agent(root, "sre", body=agent_md("sre").replace(
        "<!-- agentic-org: v0.1.0 source=.claude/agents/sre.md -->",
        "<!-- agentic-org: v0.1 source= -->",
    ))
    assert run(root) == 1
    assert "missing agentic-org provenance header" in capsys.readouterr().err


def test_project_owned_marker_is_not_accepted_on_a_team_yaml(tmp_path: Path, capsys) -> None:
    """Only agents may be generated. Everything else came from a library template and
    must say which one, or /org-update cannot reason about it."""
    root = make_valid_org(tmp_path)
    target = root / ".claude" / "teams" / "dev.yaml"
    target.write_text(target.read_text().replace(
        "# agentic-org: v0.1.0 source=.claude/teams/TEMPLATE.yaml",
        "# agentic-org: project-owned",
    ))
    assert run(root) == 1
    assert "dev.yaml: missing agentic-org provenance header" in capsys.readouterr().err


def test_project_owned_agent_name_not_matching_filename_stem_fails(tmp_path: Path, capsys) -> None:
    root = make_valid_org(tmp_path)
    add_agent(root, "stripe-expert", body=project_owned_agent_md("stripe-expert").replace(
        "name: stripe-expert", "name: stripe"
    ))
    assert run(root) == 1
    err = capsys.readouterr().err
    assert "stripe-expert.md" in err and "filename stem" in err


def test_project_owned_agent_without_description_fails(tmp_path: Path, capsys) -> None:
    """The description IS the routing logic — a generated agent is unroutable without it."""
    root = make_valid_org(tmp_path)
    add_agent(root, "stripe-expert", body=project_owned_agent_md("stripe-expert").replace(
        "description: test agent for stripe-expert duties\n", ""
    ))
    assert run(root) == 1
    assert "description is empty or missing" in capsys.readouterr().err


def test_project_owned_agent_missing_from_registry_fails(tmp_path: Path, capsys) -> None:
    root = make_valid_org(tmp_path)
    add_agent(root, "stripe-expert", body=project_owned_agent_md("stripe-expert"), register=False)
    assert run(root) == 1
    err = capsys.readouterr().err
    assert "AGENTS.md" in err and "stripe-expert" in err


def test_project_owned_agent_with_unfilled_project_context_fails(tmp_path: Path, capsys) -> None:
    root = make_valid_org(tmp_path)
    add_agent(root, "stripe-expert", body=project_owned_agent_md("stripe-expert").replace(
        "Stack: python; tests via pytest; code in src/.",
        "> Filled by /org-init with project-specific context.",
    ))
    assert run(root) == 1
    assert "library placeholder" in capsys.readouterr().err


def test_project_owned_agent_on_no_roster_still_warns(tmp_path: Path, capsys) -> None:
    """Roster membership is enforced identically: being generated is not a free pass."""
    root = make_valid_org(tmp_path)
    add_agent(root, "stripe-expert", body=project_owned_agent_md("stripe-expert"), roster=False)
    assert run(root) == 0
    err = capsys.readouterr().err
    assert "warning:" in err and "stripe-expert.md" in err and "on no team roster" in err


# --- advisory teams: gates are validated against what advisory actually runs ---

ADVISORY_TEAM = """# agentic-org: v0.1.0 source=.claude/teams/TEMPLATE.yaml
name: product
type: advisory
output: document
mission: Decide what to build and why, as reviewed written recommendations.
roster:
  lead: tech-lead
  specialists: [backend-expert]
  test: code-reviewer
ownership:
  - docs/product/
context_pack: context-packs/product.md
gates: [critique]
budget_defaults: { small: 60000, medium: 150000, large: 300000 }
routing: {}
"""

ADVISORY_PACK = (
    "# Context Pack — product\n"
    + PROV.format(src=".claude/teams/context-packs/TEMPLATE.md")
    + "\n> Staleness: refreshed 2026-07-25 (org-init)\n\n"
    "## Map\n- Product docs: `docs/product/`\n\n"
    "## Trip-wires\n- none yet\n\n"
    "## Current state\n- fresh org — nothing in flight\n"
)


def add_advisory_team(root: Path) -> Path:
    """Wire a second, ADVISORY team alongside the delivery one."""
    claude = root / ".claude"
    (root / "docs" / "product").mkdir(parents=True)
    path = claude / "teams" / "product.yaml"
    path.write_text(ADVISORY_TEAM)
    (claude / "teams" / "context-packs" / "product.md").write_text(ADVISORY_PACK)
    (claude / "teams" / "memory" / "product.md").write_text(
        "# Team lessons — product\n" + PROV.format(src=".claude/teams/memory/TEMPLATE.md") + "\n"
    )
    return path


def test_advisory_team_with_a_critique_gate_passes(tmp_path: Path) -> None:
    """The claim the template has been making for two releases must now validate."""
    root = make_valid_org(tmp_path)
    add_advisory_team(root)
    assert run(root) == 0


def test_advisory_team_declaring_ci_green_fails(tmp_path: Path, capsys) -> None:
    """An advisory run opens no PR, so ci-green names a check it can never satisfy."""
    root = make_valid_org(tmp_path)
    target = add_advisory_team(root)
    target.write_text(target.read_text().replace(
        "gates: [critique]", "gates: [code-review, ci-green]"
    ))
    assert run(root) == 1
    err = capsys.readouterr().err
    assert "product.yaml" in err and "advisory team's gates must be [critique]" in err


def test_delivery_team_is_still_held_to_ci_green(tmp_path: Path, capsys) -> None:
    """Relaxing the rule for advisory must not relax it for delivery."""
    root = make_valid_org(tmp_path)
    target = root / ".claude" / "teams" / "dev.yaml"
    target.write_text(target.read_text().replace(
        "gates: [code-review, ci-green]", "gates: [code-review]"
    ))
    assert run(root) == 1
    err = capsys.readouterr().err
    assert "dev.yaml" in err and "delivery team's gates must be [code-review, ci-green]" in err


def test_delivery_team_cannot_borrow_the_advisory_gate(tmp_path: Path) -> None:
    root = make_valid_org(tmp_path)
    target = root / ".claude" / "teams" / "dev.yaml"
    target.write_text(target.read_text().replace(
        "gates: [code-review, ci-green]", "gates: [critique]"
    ))
    assert run(root) == 1


def test_type_and_output_must_agree(tmp_path: Path, capsys) -> None:
    """team-run.js branches on `output` alone, so a yaml whose type contradicts it
    would run as a mode nobody declared."""
    root = make_valid_org(tmp_path)
    target = add_advisory_team(root)
    target.write_text(target.read_text().replace("type: advisory", "type: delivery"))
    assert run(root) == 1
    err = capsys.readouterr().err
    assert "disagree" in err and "product.yaml" in err
