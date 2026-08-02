"""Plugin skills: frontmatter, plugin-root references, validator gate wired."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import validate_org  # noqa: E402


def read_skill(name: str) -> str:
    return (ROOT / "skills" / name / "SKILL.md").read_text()


def test_org_init_skill() -> None:
    text = read_skill("org-init")
    assert text.startswith("---")
    assert "name: org-init" in text
    assert "description:" in text
    assert "${CLAUDE_PLUGIN_ROOT}" in text
    assert "validate_org.py" in text
    assert "PROJECT-CONTEXT:BEGIN" in text
    assert "NEVER silently overwrite" in text


def test_org_init_staffs_the_generalist_when_no_specialist_fits() -> None:
    """Roster selection must actually reach `software-engineer`, or it is never staffed.

    The library can carry a stack-agnostic implementer and still never use it: the
    delivery row of the roster table is what the wizard reads, and if that row only
    lists the four web-service specialists, a game/CLI/library repo still gets the
    least-wrong one. This pins the selection rule, not just the agent's existence.
    """
    text = read_skill("org-init")
    assert "software-engineer" in text, "the generalist must appear in roster selection"
    assert "no web/API/DB surface" in text, (
        "the selection rule must key on what the step-4 scan found, not on the stack's name"
    )


def test_org_init_generates_integration_agents_only_from_file_evidence() -> None:
    """Generation must be driven by the repo, never by the interview.

    The wizard curates roles and generates integrations; the integration axis is
    unbounded, so nothing but evidence in the repo can bound it. If the skill can be
    read as "the user said they use Stripe, so staff stripe-expert", it will invent
    agents for dependencies the project does not actually use.
    """
    text = read_skill("org-init")
    assert "A guess is not evidence" in text, (
        "the evidence rule must be stated outright, not implied"
    )
    for manifest in ("package.json", "pyproject.toml", "go.mod", "Gemfile", "Cargo.toml"):
        assert manifest in text, f"the scan must name {manifest} as a place evidence lives"
    assert "path:line" in text, "each candidate must carry a citable location"
    assert "appears only in a lockfile" in text, (
        "an unused transitive dependency must not become a staffed agent, and a lockfile "
        "entry is the exact shape that mistake takes"
    )
    assert "agentic-org: project-owned" in text, (
        "generated agents need the marker, or they fail validate_org.py's provenance check"
    )


def test_the_marker_org_init_writes_is_the_one_validate_org_accepts() -> None:
    """Documented-but-unimplemented is this project's recurring failure mode.

    /org-init dictates a literal marker line; validate_org.py decides what counts as
    provenance. If the two drift, every generated agent fails the wizard's own step-8
    gate — and it fails at handover, after the work is done.
    """
    marker = next(
        line.strip()
        for line in read_skill("org-init").splitlines()
        if line.strip().startswith("<!-- agentic-org: project-owned")
    )
    assert validate_org.PROJECT_OWNED_RE.search(marker), (
        f"the skill tells the wizard to write {marker!r}, which the validator rejects"
    )
    assert not validate_org.PROVENANCE_RE.search(marker), (
        "the two kinds must stay distinct — a project-owned marker must not also read as "
        "a library `source=` header, or /org-update would try to diff it against nothing"
    )


def test_org_init_forbids_generating_role_duplicates() -> None:
    """Curate roles, generate integrations — the whole design collapses if roles leak in.

    A second backend agent splits routing between two identities with the same remit,
    and the decompose stage picks between them arbitrarily.
    """
    text = read_skill("org-init")
    assert "NEVER generate one of these" in text, "the role axis must be explicitly off-limits"
    assert "backend-expert-2" in text or "payments-backend" in text, (
        "name the concrete shape of the mistake, not just the principle"
    )
    assert "software-engineer" in text, (
        "the escape hatch when no library role fits is the generalist, not a new agent"
    )


def test_org_init_caps_the_number_of_generated_agents() -> None:
    """A repo with 60 dependencies must not produce 60 agents."""
    text = read_skill("org-init")
    assert "hard cap" in text.lower(), "the cap must be stated as a rule, not a suggestion"
    assert "at most 3 per team" in text and "at most 5 across the whole org" in text, (
        "the cap must be a number the wizard can actually apply"
    )
    assert "Propose before generating" in text, (
        "the user picks which few matter — silent generation defeats the cap"
    )


def test_recipe_new_skill() -> None:
    """The authoring skill must carry the invariants, not just describe the format.

    Workflow scripts cannot be executed by node or pytest, so nothing catches a bad
    recipe at author time except this skill and the structural tests it tells the
    author to write. Every rule pinned here was paid for by a real defect.
    """
    text = read_skill("recipe-new")
    assert text.startswith("---")
    assert "name: recipe-new" in text
    assert "description:" in text
    for banned in ("Date.now", "Math.random"):
        assert banned in text, f"must name {banned} as forbidden — it breaks Workflow resume"
    assert "INCOMPLETE" in text, "the reserved degraded verdict must be taught"
    assert "filter(Boolean)" in text, "must warn how a dead agent silently vanishes"
    assert "mutation" in text.lower(), (
        "must tell the author to mutation-check their own test — a test whose "
        "assertion cannot fail is worse than no test, and these tests are the only gate"
    )


def test_org_update_skill() -> None:
    text = read_skill("org-update")
    assert text.startswith("---")
    assert "name: org-update" in text
    assert "${CLAUDE_PLUGIN_ROOT}" in text
    assert "provenance" in text.lower()
    assert "validate_org.py" in text
    assert "Never" in text  # never-overwrite-silently doctrine present


def test_org_update_never_syncs_project_owned_agents() -> None:
    """A generated agent has no upstream baseline, so there is nothing to sync it against.

    Classifying it as anything else means /org-update either diffs it against a file
    that does not exist, or reports it forever as unexplained drift.
    """
    text = read_skill("org-update")
    assert "agentic-org: project-owned" in text, "the marker must be a recognised classification"
    assert "NEVER auto-updated, and never reported as drift" in text
    assert "no upstream library file" in text, "say WHY, not just what"


def test_org_init_detects_agents_in_subdirectories() -> None:
    """The prior-Claude-Code check must recurse.

    Measured on a real project during the first pilot: a flat `ls .claude/agents/*.md`
    reported 2 agents where 33 existed, because that project keeps them in
    subdirectories (agents/engineering/, agents/ai_ml/, agents/business/). A 94%
    under-report makes an organised project look nearly clean to the guard whose
    entire job is noticing it is not.
    """
    text = read_skill("org-init")
    assert "find .claude/agents -name '*.md'" in text, (
        "2c must find agents recursively — a flat glob misses subdirectories"
    )
    assert "ls .claude/agents/*.md .claude/commands/*.md" not in text, (
        "the non-recursive glob must be gone, not merely supplemented"
    )


def test_org_init_treats_a_duplicate_agent_name_as_a_collision() -> None:
    """Path collisions alone are not enough.

    An existing `agents/engineering/backend-expert.md` does not collide by path with
    a materialized `agents/backend-expert.md` — so without a name-level check the
    project ends up with two identities sharing one name, and nothing determines
    which one a team lead dispatches.
    """
    text = read_skill("org-init")
    assert "Name collisions" in text
    assert "same *name* already exist anywhere in" in text


def test_org_init_never_deletes_a_pre_existing_state_ignore_file() -> None:
    """Preserve mode may add, never remove.

    Measured on the same pilot run: writing `teams/state/.gitkeep` replaced a
    pre-existing `teams/state/.gitignore`. The outcome was equivalent, but the
    wizard's guarantee is "never overwrite a pre-existing file without
    confirmation" — and deleting is strictly stronger than overwriting.
    """
    text = read_skill("org-init")
    assert "never remove\n    what is already there" in text
    assert "deleting is\n    stronger than overwriting" in text
