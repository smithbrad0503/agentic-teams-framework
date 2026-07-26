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


def test_agents_dir_readme_without_frontmatter_passes(tmp_path: Path) -> None:
    """Non-agent documentation (no YAML frontmatter) in .claude/agents/ is skipped, not rejected."""
    root = make_valid_org(tmp_path)
    (root / ".claude" / "agents" / "README.md").write_text(
        "# Agents\n\nSee individual files in this directory for role definitions.\n"
    )
    assert run(root) == 0
