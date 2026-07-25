# agentic-org v1 Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the agentic-teams-framework repo into an installable Claude Code plugin (`agentic-org`) with an `/org-init` materializing wizard, an `/org-update` sync skill, an org-level memory layer wired into the runner, and three recurring-workflow recipes.

**Architecture:** The repo root becomes the plugin root (`.claude-plugin/plugin.json` + `marketplace.json`; the repo doubles as its own marketplace). The plugin's *library* is the existing `.claude/` tree — plugin skills reference it via `${CLAUDE_PLUGIN_ROOT}/.claude/…`, so nothing is duplicated. `/org-init` interviews the user and materializes a project-owned org into the target project's `.claude/`; every generated file carries a provenance header so `/org-update` can diff library improvements in later. A deterministic Python validator (`scripts/validate_org.py`) is the wizard's final hard gate.

**Tech Stack:** Markdown skills/commands, Claude Code plugin manifest (JSON), Workflow scripts (plain JS, host-provided `agent()/parallel()/pipeline()/phase()/log()` globals), Python 3.10+ + PyYAML + pytest for validation.

**Spec:** `docs/superpowers/specs/2026-07-25-agentic-org-plugin-design.md`. One deliberate adaptation: the spec's "run the wizard against 2–3 fixture project types in pytest" is not literally possible (the wizard is agent-driven, not a Python function). It is replaced by (a) a deterministic validator with unit tests against tmp_path fixture orgs — the same checks the wizard's output must pass — and (b) a manual dogfood gate (Task 11) that runs the real wizard end-to-end before any announcement.

## Global Constraints

- Branch: create `feature/agentic-org-v1` from `docs/agentic-org-v1-spec` before Task 1; commit per task; never push to `main` (a pre-push hook may enforce this); open a PR at the end.
- Commits: conventional format `<type>: <description>`. **No `Co-Authored-By` lines, no AI attribution** (repo rule, overrides Claude Code defaults).
- Test command: `python3 -m pytest -q` from the repo root. Must be green at the end of every task. (Requires `pyyaml` and `pytest` installed; if missing: `pip3 install pytest pyyaml`.)
- Plugin name: `agentic-org`. Version: `0.1.0`. Marketplace name: `agentic-teams`.
- Context-pack hard cap: 12,000 chars. Org-memory per-file hard cap: 8,000 chars.
- Provenance header (generated files only, written by the wizard — library files do NOT carry it): markdown `<!-- agentic-org: v<version> source=<library-relative-path> -->`, YAML and JS `# agentic-org: …` / `// agentic-org: v<version> source=<library-relative-path>`. Placement: **line 1** for YAML and JS; for markdown, the line after the H1 title (or after the closing frontmatter `---` when the file has frontmatter). It must always land within the first 12 lines — that is the window both `validate_org.py` and `/org-update` scan.
- PROJECT-CONTEXT markers (exact strings): `<!-- PROJECT-CONTEXT:BEGIN -->` and `<!-- PROJECT-CONTEXT:END -->`.
- Never violate the framework invariants: the runner opens a PR and stops (never merges); the review stage is never demoted below the strongest tier. Workflow scripts must not call `Date.now()`, `Math.random()`, or argless `new Date()`.
- Working directory: `/Users/brad/Code/AI Consulting/agentic-teams-framework`.

---

### Task 1: Plugin manifest + marketplace

**Files:**
- Create: `.claude-plugin/plugin.json`
- Create: `.claude-plugin/marketplace.json`
- Test: `tests/test_plugin_manifest.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `plugin.json` with `version` field — read by the `/org-init` and `/org-update` skills (Tasks 8–9) for provenance headers. Marketplace name `agentic-teams` — used in README install instructions (Task 10).

- [ ] **Step 1: Write the failing test**

Create `tests/test_plugin_manifest.py`:

```python
"""Plugin manifest + marketplace shape, and plugin/tree command sync."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / ".claude-plugin"
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def test_plugin_manifest_shape() -> None:
    manifest = json.loads((PLUGIN_DIR / "plugin.json").read_text())
    assert manifest["name"] == "agentic-org"
    assert SEMVER.match(manifest["version"]), "version must be plain semver"
    for key in ("description", "license", "repository"):
        assert manifest.get(key), f"plugin.json missing {key}"


def test_marketplace_lists_plugin() -> None:
    marketplace = json.loads((PLUGIN_DIR / "marketplace.json").read_text())
    assert marketplace["name"] == "agentic-teams"
    entries = {p["name"]: p for p in marketplace["plugins"]}
    assert "agentic-org" in entries
    assert entries["agentic-org"]["source"] in ("./", "."), (
        "the repo root is the plugin root"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_plugin_manifest.py -q`
Expected: 2 FAILED with `FileNotFoundError` (no `.claude-plugin/` dir yet)

- [ ] **Step 3: Create the manifest files**

Create `.claude-plugin/plugin.json`:

```json
{
  "name": "agentic-org",
  "description": "Materialize a customized agentic org — teams, agents, context packs, shared org memory, and a gated PR pipeline — into your project via an interview wizard.",
  "version": "0.1.0",
  "author": {
    "name": "Bradley Smith"
  },
  "homepage": "https://github.com/smithbrad0503/agentic-teams-framework",
  "repository": "https://github.com/smithbrad0503/agentic-teams-framework",
  "license": "MIT",
  "keywords": ["agents", "teams", "orchestration", "workflows", "memory", "org"]
}
```

Create `.claude-plugin/marketplace.json`:

```json
{
  "name": "agentic-teams",
  "owner": {
    "name": "Bradley Smith"
  },
  "plugins": [
    {
      "name": "agentic-org",
      "source": "./",
      "description": "Config-driven agentic team orchestration: /org-init materializes a project-owned org; teams return gated, CI-green PRs that only humans merge."
    }
  ]
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_plugin_manifest.py -q`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add .claude-plugin/ tests/test_plugin_manifest.py
git commit -m "feat: plugin manifest and self-hosted marketplace (agentic-org)"
```

---

### Task 2: Plugin-level /team command (mirror of the tree copy)

The plugin loads commands from `commands/` at the plugin root; the manual-copy tree keeps its own copy at `.claude/commands/team.md`. Both must stay byte-identical — a sync test is the DRY guard.

**Files:**
- Create: `commands/team.md` (exact copy of `.claude/commands/team.md`)
- Modify: `tests/test_plugin_manifest.py` (append sync test)

**Interfaces:**
- Consumes: `.claude/commands/team.md` (existing).
- Produces: the sync invariant — **any future edit to either copy must be applied to both** (Task 5 relies on this).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_plugin_manifest.py`:

```python
def test_plugin_team_command_in_sync() -> None:
    plugin_copy = (ROOT / "commands" / "team.md").read_text()
    tree_copy = (ROOT / ".claude" / "commands" / "team.md").read_text()
    assert plugin_copy == tree_copy, (
        "commands/team.md (plugin) and .claude/commands/team.md (manual-copy tree) "
        "must stay byte-identical — edit both"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_plugin_manifest.py::test_plugin_team_command_in_sync -q`
Expected: FAIL with `FileNotFoundError` (`commands/team.md` missing)

- [ ] **Step 3: Create the mirror**

```bash
mkdir -p commands && cp .claude/commands/team.md commands/team.md
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_plugin_manifest.py -q`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add commands/team.md tests/test_plugin_manifest.py
git commit -m "feat: expose /team as a plugin command (synced mirror of the tree copy)"
```

---

### Task 3: PROJECT-CONTEXT blocks in every library agent

**Files:**
- Create: `scripts/add_project_context_blocks.py`
- Modify: every `.claude/agents/**/*.md` except `AGENTS.md` (24 files, via the script)
- Test: `tests/test_agent_library.py`

**Interfaces:**
- Consumes: nothing.
- Produces: the marker pair `<!-- PROJECT-CONTEXT:BEGIN -->` / `<!-- PROJECT-CONTEXT:END -->` present exactly once in every library agent, with placeholder text containing the sentinel string `Filled by /org-init` — the wizard (Task 8) replaces the block body; the validator (Task 7) rejects materialized agents that still contain the sentinel.

- [ ] **Step 1: Write the failing test**

Create `tests/test_agent_library.py`:

```python
"""Every library agent carries yaml frontmatter and exactly one PROJECT-CONTEXT block."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / ".claude" / "agents"
BEGIN = "<!-- PROJECT-CONTEXT:BEGIN -->"
END = "<!-- PROJECT-CONTEXT:END -->"


def agent_files() -> list[Path]:
    return [p for p in sorted(AGENTS.rglob("*.md")) if p.name != "AGENTS.md"]


@pytest.mark.parametrize("path", agent_files(), ids=lambda p: p.stem)
def test_agent_has_one_project_context_block(path: Path) -> None:
    text = path.read_text()
    assert text.startswith("---"), f"{path.name}: missing yaml frontmatter"
    assert text.count(BEGIN) == 1, f"{path.name}: needs exactly one BEGIN marker"
    assert text.count(END) == 1, f"{path.name}: needs exactly one END marker"
    assert text.index(BEGIN) < text.index(END), f"{path.name}: markers out of order"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_agent_library.py -q`
Expected: 24 FAILED (no markers yet)

- [ ] **Step 3: Write the insertion script**

Create `scripts/add_project_context_blocks.py`:

```python
#!/usr/bin/env python3
"""Append the PROJECT-CONTEXT block to every library agent missing it.

Idempotent: files that already contain the BEGIN marker are skipped.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / ".claude" / "agents"

BLOCK = """
## Project Context

<!-- PROJECT-CONTEXT:BEGIN -->
> Filled by /org-init with project-specific context: stack, key paths for this
> agent's remit, project commands, and conventions. Until materialized, this
> agent is generic.
<!-- PROJECT-CONTEXT:END -->
"""


def main() -> None:
    changed = []
    for path in sorted(AGENTS.rglob("*.md")):
        if path.name == "AGENTS.md":
            continue
        text = path.read_text()
        if "PROJECT-CONTEXT:BEGIN" in text:
            continue
        path.write_text(text.rstrip() + "\n" + BLOCK)
        changed.append(path.name)
    print(f"updated {len(changed)} agent file(s): {', '.join(changed) or 'none'}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the script, then the tests**

Run: `python3 scripts/add_project_context_blocks.py`
Expected: `updated 24 agent file(s): …`

Run: `python3 -m pytest tests/test_agent_library.py -q`
Expected: 24 passed

Run the script a second time and confirm it prints `updated 0 agent file(s): none` (idempotence).

- [ ] **Step 5: Commit**

```bash
git add scripts/add_project_context_blocks.py tests/test_agent_library.py .claude/agents/
git commit -m "feat: PROJECT-CONTEXT injection blocks in every library agent"
```

---

### Task 4: Org-memory seed files

**Files:**
- Create: `.claude/org-memory/decisions.md`
- Create: `.claude/org-memory/architecture.md`
- Create: `.claude/org-memory/lessons.md`
- Test: `tests/test_org_memory.py`

**Interfaces:**
- Consumes: nothing.
- Produces: canonical first-line headers — `# Org decisions`, `# Org architecture facts`, `# Org lessons` — and the exact heading `## Candidates (pending curation)` in `lessons.md`. The runner (Task 5) appends candidate lines under that heading; the validator (Task 7) asserts these headers verbatim.

- [ ] **Step 1: Write the failing test**

Create `tests/test_org_memory.py`:

```python
"""Org-memory seeds: canonical headers, size caps, candidates section present."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OM = ROOT / ".claude" / "org-memory"
MAX_CHARS = 8_000
HEADERS = {
    "decisions.md": "# Org decisions",
    "architecture.md": "# Org architecture facts",
    "lessons.md": "# Org lessons",
}


@pytest.mark.parametrize("fname", sorted(HEADERS))
def test_seed_header_and_cap(fname: str) -> None:
    text = (OM / fname).read_text()
    assert text.splitlines()[0] == HEADERS[fname], f"{fname}: bad canonical header"
    assert len(text) <= MAX_CHARS, f"{fname}: over the {MAX_CHARS}-char cap"


def test_lessons_candidates_section() -> None:
    assert "## Candidates (pending curation)" in (OM / "lessons.md").read_text()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_org_memory.py -q`
Expected: 4 FAILED (`FileNotFoundError`)

- [ ] **Step 3: Create the seeds**

Create `.claude/org-memory/decisions.md`:

```markdown
# Org decisions
> Cross-team decisions with date and rationale. Injected into every team-run's
> decompose and review stages. Curated by humans in the cockpit — runs never
> write here. HARD CAP ~8,000 chars: prune superseded decisions, don't append forever.

<!-- Shape: - YYYY-MM-DD — <decision>. Why: <one line>. -->
```

Create `.claude/org-memory/architecture.md`:

```markdown
# Org architecture facts
> Durable, cross-team facts about the system: boundaries, invariants, contracts.
> Not a design doc — one load-bearing line each. Injected into every team-run's
> decompose and review stages. HARD CAP ~8,000 chars.

<!-- Shape: - <subsystem>: <the invariant or contract a wrong change would break>. -->
```

Create `.claude/org-memory/lessons.md`:

```markdown
# Org lessons
> Cross-team lessons, curated from run candidates below. Per-team lessons stay in
> `.claude/teams/memory/<team>.md` — only durable, cross-team ones graduate here.
> HARD CAP ~8,000 chars.

## Candidates (pending curation)
<!-- team-run Report stages append `- [ ] (<runId>) (<stage>) <lesson>` lines here,
     uncommitted. Cockpit curates: promote above this heading, or delete. -->
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_org_memory.py -q`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add .claude/org-memory/ tests/test_org_memory.py
git commit -m "feat: org-memory seed files (decisions, architecture, lessons)"
```

---

### Task 5: Runner org-memory injection + orgLessons pipeline

Wire the org-memory layer into `team-run.js` (inject at decompose + review; collect `orgLessons`; Report appends candidates) and teach the `/team` dispatch procedure to resolve it. **Both `team.md` copies must get the identical edit** (sync test from Task 2 enforces it).

**Files:**
- Modify: `.claude/workflows/team-run.js`
- Modify: `.claude/commands/team.md` and `commands/team.md` (identical edit)
- Test: `tests/test_runner_contract.py`

**Interfaces:**
- Consumes: org-memory canonical file names from Task 4 (`decisions.md`, `architecture.md`, `lessons.md`; heading `## Candidates (pending curation)`).
- Produces: config contract field `orgMemory: string` (optional, `""` when absent) — the `/org-init`-materialized runner is a verbatim copy, so projects get this automatically; report field `orgLessons: string[]` accepted from every staged agent.

- [ ] **Step 1: Write the failing test**

Create `tests/test_runner_contract.py`:

```python
"""Structural contract checks on team-run.js and the /team command copies.

The runner is a Workflow script (host globals, top-level return) — it cannot be
executed under node or pytest. These greps pin the load-bearing structures; the
dogfood dry-run exercises the real behavior.
"""

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_runner_contract.py -q`
Expected: `test_core_invariant_intact` passes; the other 4 FAIL

- [ ] **Step 3: Edit `team-run.js` — config contract comment**

Find (in the header comment block):

```
//     pack:      string   — the FULL context-pack markdown (pointers, trip-wires)
//     memory:    string   — the FULL team-lessons markdown ("" if absent)
```

Replace with:

```
//     pack:      string   — the FULL context-pack markdown (pointers, trip-wires)
//     memory:    string   — the FULL team-lessons markdown ("" if absent)
//     orgMemory: string   — concatenated .claude/org-memory/ markdown ("" if absent)
```

- [ ] **Step 4: Edit `team-run.js` — collectors**

Find:

```js
const trace = []
const stages = []
const lessons = []
```

Replace with:

```js
const trace = []
const stages = []
const lessons = []
const orgLessons = []
```

Find (inside `call()`):

```js
  if (res && Array.isArray(res.lessons)) lessons.push(...res.lessons.map((l) => ({ stage: label, lesson: l })))
  return res
```

Replace with:

```js
  if (res && Array.isArray(res.lessons)) lessons.push(...res.lessons.map((l) => ({ stage: label, lesson: l })))
  if (res && Array.isArray(res.orgLessons)) orgLessons.push(...res.orgLessons.map((l) => ({ stage: label, lesson: l })))
  return res
```

- [ ] **Step 5: Edit `team-run.js` — schemas**

In `CONFIG_SCHEMA`, find:

```js
    memory: { type: 'string', description: 'full team-lessons markdown ("" if absent)' },
```

Replace with:

```js
    memory: { type: 'string', description: 'full team-lessons markdown ("" if absent)' },
    orgMemory: { type: 'string', description: 'concatenated org-memory markdown ("" if absent)' },
```

(`required` stays unchanged — `orgMemory` is optional for backward compatibility.)

Add the `orgLessons` property to **four** schemas. In `PLAN_SCHEMA`, `BUILD_SCHEMA`, `DOCS_SCHEMA`, and `REVIEW_SCHEMA`, find each schema's line:

```js
    lessons: { type: 'array', items: { type: 'string' } },
```

Replace each occurrence (use `replace_all` or edit all four) with:

```js
    lessons: { type: 'array', items: { type: 'string' } },
    orgLessons: { type: 'array', items: { type: 'string' }, description: 'durable CROSS-TEAM facts/decisions (rare; usually empty)' },
```

- [ ] **Step 6: Edit `team-run.js` — Setup resolve prompt**

Find:

```
4. .claude/teams/memory/${A.team}.md (if missing, use "")

Return: mission, roster, ownership from the team yaml; routing = the global defaults with the team yaml's routing overrides merged on top (team override wins per stage class); pack = the FULL context-pack markdown; memory = the FULL memory markdown.`,
```

Replace with:

```
4. .claude/teams/memory/${A.team}.md (if missing, use "")
5. .claude/org-memory/decisions.md + architecture.md + lessons.md (concatenate in that order; if the directory is absent, use "")

Return: mission, roster, ownership from the team yaml; routing = the global defaults with the team yaml's routing overrides merged on top (team override wins per stage class); pack = the FULL context-pack markdown; memory = the FULL memory markdown; orgMemory = the concatenated org-memory markdown ("" if absent).`,
```

- [ ] **Step 7: Edit `team-run.js` — GUARDRAILS orgLessons instruction**

Find:

```
- If you learn something durable a future ${A.team}-team run should know, put it in your "lessons" report field (one line each).
```

Replace with:

```
- If you learn something durable a future ${A.team}-team run should know, put it in your "lessons" report field (one line each).
- If you learn something durable that affects OTHER teams too (an org-wide decision, contract, or invariant), put it in your "orgLessons" report field instead (one line each; rare — most runs report none).
```

- [ ] **Step 8: Edit `team-run.js` — decompose prompt injection**

Find (the tail of the decompose prompt, ending just before the routing options object `{ model: dr.model`):

```
## Team context pack (${A.team})
${cfg.pack}
${cfg.memory ? `\n## Team lessons\n${cfg.memory}` : ''}`,
  { model: dr.model, effort: dr.effort, agentType: cfg.roster.lead, schema: PLAN_SCHEMA }
```

Replace with:

```
## Team context pack (${A.team})
${cfg.pack}
${cfg.memory ? `\n## Team lessons\n${cfg.memory}` : ''}
${cfg.orgMemory ? `\n## Org memory (cross-team)\n${cfg.orgMemory}` : ''}`,
  { model: dr.model, effort: dr.effort, agentType: cfg.roster.lead, schema: PLAN_SCHEMA }
```

- [ ] **Step 9: Edit `team-run.js` — review prompt injection**

Find (the tail of the review prompt):

```
## Team context pack (${A.team})
${cfg.pack}`,
    { agentType: 'code-reviewer', model: rr.model, effort: rr.effort, schema: REVIEW_SCHEMA }
```

Replace with:

```
## Team context pack (${A.team})
${cfg.pack}
${cfg.orgMemory ? `\n## Org memory (cross-team)\n${cfg.orgMemory}` : ''}`,
    { agentType: 'code-reviewer', model: rr.model, effort: rr.effort, schema: REVIEW_SCHEMA }
```

- [ ] **Step 10: Edit `team-run.js` — Report appends org-lesson candidates**

Find (in the final Report prompt):

```
${lessons.length
  ? `4. Append to .claude/teams/memory/${A.team}.md:\n\n## ${A.timestamp} ${A.ticket}\n${lessons.map((l) => `- (${l.stage}) ${l.lesson}`).join('\n')}\n\nNOTE: the memory file IS tracked by git but do NOT commit it here — memory commits ride the next framework PR.`
  : '4. No lessons this run — do not touch the memory file.'}

Do not commit or push anything. State files under state/ are gitignored runtime data.`,
```

Replace with:

```
${lessons.length
  ? `4. Append to .claude/teams/memory/${A.team}.md:\n\n## ${A.timestamp} ${A.ticket}\n${lessons.map((l) => `- (${l.stage}) ${l.lesson}`).join('\n')}\n\nNOTE: the memory file IS tracked by git but do NOT commit it here — memory commits ride the next framework PR.`
  : '4. No lessons this run — do not touch the memory file.'}

${orgLessons.length
  ? `5. Append to .claude/org-memory/lessons.md, directly under the "## Candidates (pending curation)" heading (if the file or heading is missing, skip this step and say so):\n${orgLessons.map((l) => `- [ ] (${A.runId}) (${l.stage}) ${l.lesson}`).join('\n')}\n\nNOTE: org-memory files are tracked by git but do NOT commit them — curation commits are human.`
  : '5. No org-lesson candidates this run — do not touch .claude/org-memory/.'}

Do not commit or push anything. State files under state/ are gitignored runtime data.`,
```

- [ ] **Step 11: Edit BOTH `team.md` copies — dispatch step 4**

In `.claude/commands/team.md` AND `commands/team.md`, find:

```
4. **Resolve config**: Read `.claude/teams/<team>.yaml`, `.claude/teams/model-routing.yaml`,
   the pack file named by `context_pack`, and `.claude/teams/memory/<team>.md`. Build
   `config = {mission, roster, ownership, routing, pack, memory}` where `routing` =
   global `defaults` with the team yaml's `routing` overrides merged on top (team wins).
```

Replace (in both files, identically) with:

```
4. **Resolve config**: Read `.claude/teams/<team>.yaml`, `.claude/teams/model-routing.yaml`,
   the pack file named by `context_pack`, `.claude/teams/memory/<team>.md`, and the
   `.claude/org-memory/` files (decisions.md + architecture.md + lessons.md concatenated
   in that order; "" if the directory is absent). Build
   `config = {mission, roster, ownership, routing, pack, memory, orgMemory}` where `routing` =
   global `defaults` with the team yaml's `routing` overrides merged on top (team wins).
```

- [ ] **Step 12: Run the full suite**

Run: `python3 -m pytest -q`
Expected: all passed (including the Task 2 sync test and all 5 runner-contract tests)

- [ ] **Step 13: Commit**

```bash
git add .claude/workflows/team-run.js .claude/commands/team.md commands/team.md tests/test_runner_contract.py
git commit -m "feat: org-memory injection at decompose/review + orgLessons candidate pipeline"
```

---

### Task 6: Workflow recipes (health-check, retro, audit)

**Files:**
- Create: `.claude/workflows/recipes/health-check.js`
- Create: `.claude/workflows/recipes/retro.js`
- Create: `.claude/workflows/recipes/audit.js`
- Test: `tests/test_recipes.py`

**Interfaces:**
- Consumes: Workflow host globals (`agent`, `parallel`, `pipeline`, `phase`, `log`, `args`) — same contract as `team-run.js`.
- Produces: three recipe scripts the `/org-init` wizard (Task 8) offers to copy into projects. All take `args.timestamp` from the dispatcher (scripts cannot call `Date`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_recipes.py`:

```python
"""Recipe workflow scripts: meta literal present, name matches stem, no wall-clock calls."""

from pathlib import Path

import pytest

RECIPES = Path(__file__).resolve().parents[1] / ".claude" / "workflows" / "recipes"
NAMES = ["health-check", "retro", "audit"]


@pytest.mark.parametrize("name", NAMES)
def test_recipe_shape(name: str) -> None:
    text = (RECIPES / f"{name}.js").read_text()
    assert "export const meta" in text, f"{name}: missing meta export"
    assert f"name: '{name}'" in text, f"{name}: meta.name must equal the filename stem"
    for banned in ("Date.now", "Math.random", "new Date("):
        assert banned not in text, f"{name}: {banned} breaks Workflow resume"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_recipes.py -q`
Expected: 3 FAILED (`FileNotFoundError`)

- [ ] **Step 3: Create `health-check.js`**

Create `.claude/workflows/recipes/health-check.js`:

```js
export const meta = {
  name: 'health-check',
  description: 'Run a configured list of read-only health checks in parallel and return a red/green report.',
  phases: [{ title: 'Check', detail: 'one read-only agent per configured check' }],
}

// ---- args contract -------------------------------------------------------
// {
//   checks: [{ name: 'api-up', instructions: 'curl the /health endpoint …' }, …],
//   timestamp: '2026-01-01T10:30:00-05:00',   // dispatcher-generated (no Date in scripts)
// }
// Checks are project-specific: keep them in a cockpit note or a small
// .claude/workflows/health-checks.json the dispatcher reads and passes in.
let A = args || {}
if (typeof A === 'string') {
  try {
    A = JSON.parse(A)
  } catch (e) {
    return { error: 'health-check: args arrived as an unparseable string — pass a JSON object' }
  }
}
if (!Array.isArray(A.checks) || !A.checks.length) {
  return { error: 'health-check: args.checks must be a non-empty array of {name, instructions}' }
}

const CHECK_SCHEMA = {
  type: 'object',
  properties: {
    ok: { type: 'boolean' },
    detail: { type: 'string', description: 'one line of evidence (≤300 chars, single line)' },
  },
  required: ['ok', 'detail'],
}

phase('Check')
const results = await parallel(
  A.checks.map((c) => () =>
    agent(
      `Health check "${c.name}". READ-ONLY: run commands and read files to verify, but change NOTHING and deploy NOTHING.\n\n${c.instructions}\n\nReturn ok=true only if the check genuinely passes; detail = one line of evidence (≤300 chars, single line).`,
      { label: `check:${c.name}`, phase: 'Check', schema: CHECK_SCHEMA }
    ).then((r) => ({ name: c.name, ok: !!(r && r.ok), detail: (r && r.detail) || 'check agent returned no report' }))
  )
)
const settled = results.map((r, i) => r || { name: A.checks[i].name, ok: false, detail: 'check agent errored' })
const failing = settled.filter((r) => !r.ok)
log(`health-check: ${settled.length - failing.length}/${settled.length} green`)
return { timestamp: A.timestamp || '', green: failing.length === 0, results: settled, failing }
```

- [ ] **Step 4: Create `retro.js`**

Create `.claude/workflows/recipes/retro.js`:

```js
export const meta = {
  name: 'retro',
  description: 'Summarize recent team-runs into a retro doc, flagging lessons worth graduating into context packs.',
  phases: [{ title: 'Write', detail: 'read run telemetry + memory, write docs/retros/<stamp>.md' }],
}

// ---- args contract -------------------------------------------------------
// {
//   timestamp: '2026-01-01T10:30:00-05:00',  // dispatcher-generated (no Date in scripts)
//   lookback?: 15,                            // max recent runs to review
// }
let A = args || {}
if (typeof A === 'string') {
  try {
    A = JSON.parse(A)
  } catch (e) {
    return { error: 'retro: args arrived as an unparseable string — pass a JSON object' }
  }
}
if (!A.timestamp) return { error: 'retro: args.timestamp required (workflow scripts cannot call Date)' }

const N = A.lookback || 15
const FILE = `docs/retros/retro-${A.timestamp.replace(/[-:]/g, '').slice(0, 13)}.md`
const RETRO_SCHEMA = {
  type: 'object',
  properties: {
    path: { type: 'string' },
    highlights: { type: 'array', items: { type: 'string' }, description: '≤5 single-line takeaways' },
    graduationCandidates: { type: 'array', items: { type: 'string' }, description: 'memory lessons worth moving into a context pack' },
  },
  required: ['path', 'highlights'],
}

phase('Write')
const res = await agent(
  `Write a team-run retrospective. Work in the MAIN repo checkout (git rev-parse --show-toplevel; absolute paths).

1. Read the ${N} most recent run files in .claude/teams/state/runs/ (by filename), the tail of .claude/teams/state/events.jsonl, every .claude/teams/memory/*.md, and .claude/org-memory/lessons.md if present.
2. Write ${FILE} (mkdir -p docs/retros) covering: run volume and outcomes by team, gate-round stats, recurring must-fix themes, blocked/stalemate runs needing attention, and which memory lessons look durable enough to graduate into a context pack's Trip-wires section.
3. Do NOT edit context packs, memory files, or org-memory — the retro RECOMMENDS graduations; a human applies them.
4. Do not commit or push anything.

Return: path (the file you wrote), highlights (≤5 single-line takeaways, each ≤300 chars), graduationCandidates (lesson lines worth promoting).`,
  { label: 'retro', phase: 'Write', schema: RETRO_SCHEMA }
)
if (!res) return { error: 'retro: retro agent returned no report' }
log(`retro: wrote ${res.path}`)
return { timestamp: A.timestamp, ...res }
```

- [ ] **Step 5: Create `audit.js`**

Create `.claude/workflows/recipes/audit.js`:

```js
export const meta = {
  name: 'audit',
  description: 'Sweep a target area against a checklist with parallel read-only auditors, then adversarially verify findings.',
  phases: [
    { title: 'Audit', detail: 'one auditor per checklist item' },
    { title: 'Verify', detail: 'adversarial refutation of each finding' },
  ],
}

// ---- args contract -------------------------------------------------------
// {
//   target: 'src/auth/ (or a subsystem description)',
//   checklist: ['secrets in code', 'unvalidated input reaching queries', …],
//   timestamp: '2026-01-01T10:30:00-05:00',
// }
let A = args || {}
if (typeof A === 'string') {
  try {
    A = JSON.parse(A)
  } catch (e) {
    return { error: 'audit: args arrived as an unparseable string — pass a JSON object' }
  }
}
if (!A.target || !Array.isArray(A.checklist) || !A.checklist.length) {
  return { error: 'audit: args.target and a non-empty args.checklist are required' }
}

const FINDINGS_SCHEMA = {
  type: 'object',
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          file: { type: 'string' },
          issue: { type: 'string', description: 'one line, ≤300 chars' },
          severity: { type: 'string', enum: ['high', 'medium', 'low'] },
        },
        required: ['file', 'issue', 'severity'],
      },
    },
  },
  required: ['findings'],
}
const VERDICT_SCHEMA = {
  type: 'object',
  properties: {
    real: { type: 'boolean' },
    reason: { type: 'string', description: 'one line, ≤300 chars' },
  },
  required: ['real', 'reason'],
}

const audited = await pipeline(
  A.checklist,
  (item) =>
    agent(
      `Audit ${A.target} for: ${item}\n\nREAD-ONLY: inspect code and config, change NOTHING. Report concrete findings only (file, one-line issue, severity). Zero findings is a valid, good result — do not invent issues.`,
      { label: `audit:${String(item).slice(0, 40)}`, phase: 'Audit', schema: FINDINGS_SCHEMA }
    ),
  (r) =>
    parallel(
      ((r && r.findings) || []).map((f) => () =>
        agent(
          `Adversarially verify this audit finding in ${A.target} — try to REFUTE it:\n${f.file}: ${f.issue} (${f.severity})\n\nREAD-ONLY. Return real=true only if the issue genuinely exists as described; when uncertain, real=false.`,
          { label: `verify:${f.file}`, phase: 'Verify', schema: VERDICT_SCHEMA }
        ).then((v) => ({ ...f, verified: !!(v && v.real), verifyReason: (v && v.reason) || '' }))
      )
    )
)
const confirmed = audited
  .filter(Boolean)
  .flat()
  .filter(Boolean)
  .filter((f) => f.verified)
log(`audit: ${confirmed.length} confirmed finding(s) on ${A.target}`)
return { timestamp: A.timestamp || '', target: A.target, confirmed }
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_recipes.py -q`
Expected: 3 passed

- [ ] **Step 7: Commit**

```bash
git add .claude/workflows/recipes/ tests/test_recipes.py
git commit -m "feat: recurring-workflow recipes (health-check, retro, audit)"
```

---

### Task 7: `scripts/validate_org.py` — the materialization gate

**Files:**
- Create: `scripts/validate_org.py`
- Test: `tests/test_validate_org.py`

**Interfaces:**
- Consumes: canonical strings from Tasks 3–4 (markers, sentinel `Filled by /org-init`, org-memory headers, candidates heading).
- Produces: CLI `python3 scripts/validate_org.py --project-root <path>` → exit 0 (valid) / 1 (errors, one per line on stderr). The `/org-init` (Task 8) and `/org-update` (Task 9) skills call it as their final hard gate.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_validate_org.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_validate_org.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'validate_org'`

- [ ] **Step 3: Write the validator**

Create `scripts/validate_org.py`:

```python
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
        if not (claude.parent / zone).exists():
            errs.append(f"{path}: ownership zone does not exist: {zone}")
    pack_rel = cfg.get("context_pack") or ""
    if not pack_rel or not (claude / "teams" / pack_rel).is_file():
        errs.append(f"{path}: context pack missing: {pack_rel!r}")
    if cfg.get("gates") != ["code-review", "ci-green"]:
        errs.append(f"{path}: gates must be [code-review, ci-green]")
    budgets = cfg.get("budget_defaults") or {}
    if set(budgets) != {"small", "medium", "large"} or not (
        budgets.get("small", 0) < budgets.get("medium", 0) < budgets.get("large", 0)
    ):
        errs.append(f"{path}: budget_defaults must define small < medium < large")
    for stage, entry in (cfg.get("routing") or {}).items():
        if stage not in STAGE_CLASSES:
            errs.append(f"{path}: unknown routing stage class {stage!r}")
        elif not isinstance(entry, dict) or not entry.get("model") or entry.get("effort") not in VALID_EFFORTS:
            errs.append(f"{path}: bad routing entry for {stage!r}")
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
        return [f"{path}: defaults must cover exactly the stage classes {sorted(STAGE_CLASSES)}"]
    for stage, entry in defaults.items():
        if not isinstance(entry, dict) or not entry.get("model") or entry.get("effort") not in VALID_EFFORTS:
            errs.append(f"{path}: bad entry for {stage!r}")
            return errs
    if defaults["review"]["model"] != defaults["decompose"]["model"]:
        errs.append(f"{path}: review must route to the strongest tier (same model as decompose)")
    for stage, entry in defaults.items():
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_validate_org.py -q`
Expected: 8 passed

Also run the validator against the framework repo itself and confirm it *fails politely* (the library is not a materialized org — agents still carry the placeholder sentinel and no provenance):

Run: `python3 scripts/validate_org.py --project-root . ; echo "exit: $?"`
Expected: error lines + `exit: 1` (this is correct behavior — the library ≠ a materialized org)

- [ ] **Step 5: Commit**

```bash
git add scripts/validate_org.py tests/test_validate_org.py
git commit -m "feat: validate_org.py — deterministic gate for materialized orgs"
```

---

### Task 8: `/org-init` wizard skill

**Files:**
- Create: `skills/org-init/SKILL.md`
- Test: `tests/test_skills.py`

**Interfaces:**
- Consumes: `${CLAUDE_PLUGIN_ROOT}/.claude/` as the library; `plugin.json` `version` for provenance; `scripts/validate_org.py` as the hard gate; PROJECT-CONTEXT markers from Task 3; org-memory seeds from Task 4; recipes from Task 6.
- Produces: the `/org-init` user entry point.

- [ ] **Step 1: Write the failing test**

Create `tests/test_skills.py`:

```python
"""Plugin skills: frontmatter, plugin-root references, validator gate wired."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_skills.py -q`
Expected: 1 FAILED (`FileNotFoundError`)

- [ ] **Step 3: Write the skill**

Create `skills/org-init/SKILL.md`:

````markdown
---
name: org-init
description: Materialize a customized agentic org into this project. Use when the user runs /org-init or asks to set up agentic teams, generate their org, or bootstrap the agentic-teams framework in a repo.
---

# /org-init — Materialize Your Agentic Org

Interview the user, then generate a **project-owned** agentic org into the
project's `.claude/` from the plugin's library. The project owns the output —
it keeps working if the plugin is uninstalled.

- Library root (the source of everything you copy): `${CLAUDE_PLUGIN_ROOT}/.claude/`
- Plugin version (for provenance headers): the `version` field of
  `${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json`
- Provenance header, added to EVERY generated file:
  - markdown: `<!-- agentic-org: v<version> source=<library-relative-path> -->` placed
    on the line after the H1 title (or after the closing frontmatter `---` when the
    file has frontmatter)
  - yaml: `# agentic-org: v<version> source=<library-relative-path>` as line 1

## 1. Prerequisites (hard gate)

Run each check; on failure STOP and give the plain-language fix:

| Check | Command | Fix if it fails |
|---|---|---|
| Git repo | `git rev-parse --show-toplevel` | "Run this inside a git repository (`git init` first)." |
| GitHub CLI | `gh auth status` | "Install the GitHub CLI and run `gh auth login` — team-runs open PRs via `gh`." |
| Worktrees | `git worktree list` | "Your git is too old — team-runs isolate work in worktrees (git ≥ 2.5)." |
| jq | `jq --version` | "Install `jq` — the `/team` board updates use it." |

Also note (warn, don't block): if the repo has no CI configured on PRs, the
ci-green gate will report red on every run — recommend adding at least a test
workflow before the first dispatch.

## 2. Existing-org check (idempotence)

If any team yaml exists (`.claude/teams/*.yaml` excluding `TEMPLATE.yaml` and
`model-routing.yaml`): say the org already exists and offer exactly two paths —
**update** (invoke the org-update skill and stop) or **extend** (continue, but
only ADD new teams/agents/recipes; skip every file that already exists and list
the skips at the end). NEVER silently overwrite an existing org file.

## 3. Interview (one question at a time)

Use AskUserQuestion where options fit; keep it to ~6 questions:

1. **Product** — what is this project, in one sentence? (Seeds team missions and packs.)
2. **Stack** — language(s), framework(s), and the exact formatter / linter /
   type-checker / test commands. VERIFY against the repo (package.json,
   pyproject.toml, Makefile, go.mod…) instead of trusting the answer blindly.
3. **Functions** (multi-select) — which parts of the org to staff:
   delivery (code → gated PRs) · product advisory · growth/marketing · platform-ops.
4. **Model tiers** — which model identifiers this setup exposes for
   strong / mid / cheap (suggest what you know is available; these replace the
   placeholders in model-routing.yaml).
5. **Ticket convention** — Linear/Jira/GitHub-issue prefix, or free-form
   (used in dispatch examples).
6. **Recipes** (multi-select) — install recurring workflows: health-check, retro, audit.

## 4. Codebase scan (read-only)

Explore enough to draft each selected team's context pack: top-level layout,
where each candidate ownership zone lives, project commands, and 2–3 obvious
trip-wires (odd conventions, generated dirs, migration rules). POINTERS, NOT
CONTENT — never paste code into a pack.

## 5. Roster selection (curate + customize — never invent agents)

Staff teams from the library roster (`${CLAUDE_PLUGIN_ROOT}/.claude/agents/`):

| Function | Team yaml | type/output | Lead | Specialists (pick for the stack) | Test |
|---|---|---|---|---|---|
| Delivery | `dev.yaml` (split into `backend.yaml`/`frontend.yaml` only when zones are truly disjoint) | delivery/pr | tech-lead | backend-expert, frontend-expert, api-expert, database-expert — as the stack requires | qa-tester |
| Product advisory | `product.yaml` | advisory/document | product-manager | ux-designer, analytics-expert | code-reviewer (fact-check gate) |
| Growth | `growth.yaml` | advisory/document | marketing-expert | copywriter | legal-expert (compliance gate) |
| Platform-ops | `platform.yaml` | delivery/pr | tech-lead | cloud-infra-expert, sre, security-expert | qa-tester |

Always materialize `code-reviewer`, `debug-expert`, and `docs-author` even if no
roster names them — the runner hard-requires those three agentTypes.

## 6. Materialize (staging first)

Build EVERYTHING under `.claude/.org-init-staging/` first. Only after all
generation succeeds, move files into their real `.claude/` locations
(extend-mode: skip existing files and record the skip), then delete the staging
dir. A failed generation must leave the project untouched.

Generate, each file with its provenance header:

1. **Agents** → `agents/<name>.md` for every rostered agent + the three
   hard-required ones + `AGENTS.md` (copied as-is, plus provenance). For each
   agent: copy the library file, then REPLACE the body between
   `<!-- PROJECT-CONTEXT:BEGIN -->` and `<!-- PROJECT-CONTEXT:END -->` with
   project specifics — stack, the key paths for this agent's remit, project
   commands, conventions. Leave everything outside the markers untouched.
2. **Teams** → `teams/<team>.yaml` from `teams/TEMPLATE.yaml` (drop the
   template comments): name = filename stem, type/output per the table,
   one-line mission from the interview, roster, REAL ownership zones (every
   path must exist), `context_pack: context-packs/<team>.md`,
   `gates: [code-review, ci-green]`, the template's budget_defaults,
   `routing: {}`.
3. **Context packs** → `teams/context-packs/<team>.md`: first line
   `# Context Pack — <team>`, provenance on line 2, staleness line with today's
   date and "(org-init)", then `## Map` / `## Trip-wires` / `## Current state`
   from the scan. For a fresh org, Current state = "fresh org — nothing in
   flight". HARD CAP 12,000 chars.
4. **Team memory seeds** → `teams/memory/<team>.md`: first line
   `# Team lessons — <team>`, provenance on line 2.
5. **Org memory** → copy the three files from
   `${CLAUDE_PLUGIN_ROOT}/.claude/org-memory/` (keep their canonical first
   lines; provenance on line 2; keep the `## Candidates (pending curation)`
   heading in lessons.md). Seed decisions.md with 1–3 dated entries from the
   interview (stack choice, org shape).
6. **Runner** → copy `workflows/team-run.js` VERBATIM, with the provenance
   comment prepended as line 1 (`// agentic-org: v<version> source=…`, above
   `export const meta`). Change nothing else — this file is library-synced.
7. **Recipes** → copy each recipe the user selected from
   `workflows/recipes/` into `workflows/` (provenance as line 1, same as the runner).
8. **Command** → copy `commands/team.md` → `.claude/commands/team.md` with
   provenance after the H1 (the project keeps `/team` even without the plugin).
9. **Routing** → `teams/model-routing.yaml` from the library file with
   `strong` / `mid` / `cheap` replaced by the user's identifiers. NEVER give
   `review` a weaker model than `decompose`.
10. **State dir** → `teams/state/.gitkeep` (empty file).

## 7. Wire the project

Append to the project's `.gitignore` (create it if missing), only the lines not
already present:

```
.claude/teams/state/*
!.claude/teams/state/.gitkeep
```

## 8. Validate (hard gate)

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/validate_org.py" --project-root "$(git rev-parse --show-toplevel)"
```

Exit 0 required. On failure: fix every reported error and re-run. Do NOT hand
over an org that fails validation.

## 9. Hand over

Report: the org chart (`ls .claude/teams/*.yaml`), agents materialized, recipes
installed, and a first-dispatch example using the user's ticket convention:

```
/team dispatch <team> <TICKET-1> "<one concrete starter task from the interview>" small
```

Offer to commit the org on a feature branch (`chore/agentic-org-init`) — never
commit without the user's go-ahead, never push to the default branch. Close by
noting `/org-update` exists for syncing future library improvements.
````

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_skills.py -q`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add skills/org-init/ tests/test_skills.py
git commit -m "feat: /org-init wizard skill (interview -> materialize -> validate)"
```

---

### Task 9: `/org-update` sync skill

**Files:**
- Create: `skills/org-update/SKILL.md`
- Modify: `tests/test_skills.py` (append test)

**Interfaces:**
- Consumes: provenance headers written by `/org-init`; `plugin.json` version; `validate_org.py`.
- Produces: the `/org-update` user entry point (also invoked by `/org-init`'s update path).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_skills.py`:

```python
def test_org_update_skill() -> None:
    text = read_skill("org-update")
    assert text.startswith("---")
    assert "name: org-update" in text
    assert "${CLAUDE_PLUGIN_ROOT}" in text
    assert "provenance" in text.lower()
    assert "validate_org.py" in text
    assert "Never" in text  # never-overwrite-silently doctrine present
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_skills.py -q`
Expected: 1 passed, 1 FAILED

- [ ] **Step 3: Write the skill**

Create `skills/org-update/SKILL.md`:

````markdown
---
name: org-update
description: Sync library improvements from the agentic-org plugin into a previously materialized org. Use when the user runs /org-update or asks to update their agentic org after a plugin update.
---

# /org-update — Sync Library Improvements

Doctrine: **Never overwrite silently.** Every change is shown as a diff and
applied only on explicit acceptance, file by file.

## 1. Locate the org

`git rev-parse --show-toplevel`; require `.claude/teams/` with at least one
team yaml (excluding TEMPLATE.yaml / model-routing.yaml). If none: "no
materialized org here — run /org-init instead" and stop.

## 2. Build the provenance map

Scan every file under the project's `.claude/` whose first 12 lines match
`agentic-org: v<version> source=<library-relative-path>`. Record
`{file, materializedVersion, librarySource}`. Files WITHOUT a provenance header
are user-authored — never touch them. Current library version: `version` in
`${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json`.

## 3. Classify

- **Library-synced** (runner, recipes, `/team` command, AGENTS.md): the library
  file at `${CLAUDE_PLUGIN_ROOT}/<librarySource>` is the upstream. Candidate
  for update whenever it differs from the project copy (ignoring the provenance
  line itself).
- **Agents**: upstream is the library agent, BUT the project's PROJECT-CONTEXT
  block content is sacred. Proposed file = new library body with the project's
  existing block body re-inserted between the markers. Diff proposed vs project.
- **Project-owned** (team yamls, context packs, team memory, org-memory,
  model-routing): NEVER auto-updated — only mention when their library TEMPLATE
  changed materially, and let the user apply ideas by hand.

## 4. Propose and apply

For each update candidate: show a short summary + the diff (proposed vs
current). If the project copy contains edits the library doesn't explain
(hand-customization beyond the PROJECT-CONTEXT block), flag it CUSTOMIZED and
present a three-way summary instead of a clean diff. Apply ONLY accepted files;
update each applied file's provenance line to the current version.

## 5. Validate and report

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/validate_org.py" --project-root "$(git rev-parse --show-toplevel)"
```

Exit 0 required. Report applied / skipped / CUSTOMIZED-flagged files. Offer to
commit on a branch (`chore/org-update-v<version>`); never push to the default
branch.
````

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_skills.py -q`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add skills/org-update/ tests/test_skills.py
git commit -m "feat: /org-update sync skill (provenance-based, never silent)"
```

---

### Task 10: Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/setup-guide.md`
- Modify: `docs/design.md`

No new tests — run the full suite at the end to confirm nothing regressed.

- [ ] **Step 1: README — plugin install section + org-memory bullet + layout**

In `README.md`, find:

```markdown
This is an extraction of a framework that proved itself over ~30 merged PRs and 13+
team-runs on a production codebase. The machinery is generic; everything project-specific
lives in config you write (team yamls + context packs).
```

Replace with:

```markdown
This is an extraction of a framework that proved itself over ~30 merged PRs and 13+
team-runs on a production codebase. The machinery is generic; everything project-specific
lives in config you write (team yamls + context packs) — or, with the plugin, config
the `/org-init` wizard writes for you.

## Install as a plugin (recommended)

```
/plugin marketplace add smithbrad0503/agentic-teams-framework
/plugin install agentic-org@agentic-teams
```

Then, inside the project you want to staff, run `/org-init`. It interviews you
(product, stack, org functions, model tiers), scans the repo, and materializes a
customized org into `.claude/` — agents, team yamls, context packs, org memory, the
runner, and any workflow recipes you opt into. The project **owns** the output; it keeps
working if the plugin is removed. When the plugin updates, `/org-update` diffs library
improvements into your org without touching your customizations.

Prefer manual adoption? The 10-minute quickstart below still works unchanged.
```

Then find (in "## What it is"):

```markdown
- **Context packs** are the token lever — curated ~1–2k-token briefings (pointers, not code;
  trip-wires, not tutorials) injected into every agent so they don't re-explore cold.
```

Replace with:

```markdown
- **Context packs** are the token lever — curated ~1–2k-token briefings (pointers, not code;
  trip-wires, not tutorials) injected into every agent so they don't re-explore cold.
- **Org memory** (`.claude/org-memory/`) — decisions, architecture facts, and cross-team
  lessons injected into every run's decompose and review stages. Runs append candidates;
  humans curate. Per-team lessons stay in team memory.
```

Then find (in "## Layout"):

```
    memory/TEMPLATE.md          annotated team-lessons template
    state/.gitkeep              runtime board/events/telemetry live here (gitignored)
```

Replace with:

```
    memory/TEMPLATE.md          annotated team-lessons template
    state/.gitkeep              runtime board/events/telemetry live here (gitignored)
  org-memory/                   cross-team memory seeds (decisions, architecture, lessons)
  workflows/recipes/            recurring-workflow recipes (health-check, retro, audit)
```

Then find:

```
dist/
  dev-team-package/             self-contained software-developer-team subset (+ .zip)
```

Replace with:

```
dist/
  dev-team-package/             self-contained software-developer-team subset (+ .zip)
.claude-plugin/                 plugin manifest + marketplace (install: agentic-org@agentic-teams)
skills/                         /org-init (materialize an org) · /org-update (sync library changes)
commands/                       /team as a plugin command (mirror of .claude/commands/team.md)
scripts/validate_org.py         deterministic gate for materialized orgs
```

- [ ] **Step 2: setup-guide — plugin fast path**

In `docs/setup-guide.md`, find:

```markdown
Step-by-step adoption for a new project. End state: you dispatch a named team at a
ticket from one cockpit session, and it returns a code-reviewed, CI-green pull request
that a human approves and merges.
```

Replace with:

```markdown
Step-by-step adoption for a new project. End state: you dispatch a named team at a
ticket from one cockpit session, and it returns a code-reviewed, CI-green pull request
that a human approves and merges.

> **Fastest path:** install the plugin and let the wizard do steps 1–4 for you —
> `/plugin marketplace add smithbrad0503/agentic-teams-framework`, then
> `/plugin install agentic-org@agentic-teams`, then run `/org-init` in your project.
> The manual steps below remain fully supported and describe exactly what the wizard
> generates.
```

- [ ] **Step 3: design.md — org-memory subsection**

In `docs/design.md`, find the line:

```markdown
## 7. The runner
```

Insert immediately BEFORE it:

```markdown
### Org memory (the cross-team layer)

`.claude/org-memory/` holds three capped files — `decisions.md`, `architecture.md`,
`lessons.md` (≤8k chars each, same philosophy as packs: small, curated, high-signal).
The dispatcher concatenates them into `config.orgMemory`; the runner injects the result
into the **decompose** and **review** prompts only (the stages where cross-team context
changes outcomes — mutating stages stay lean). Any stage may report `orgLessons`
(cross-team, durable; rare); the Report stage appends them as `- [ ] (<runId>) …`
candidate lines under `## Candidates (pending curation)` in `lessons.md`, uncommitted.
Humans curate candidates up into the files; runs never write above that heading. One
owner per layer still holds: team memory (holding area) → context pack (team canon) →
org memory (cross-team canon).

```

- [ ] **Step 4: Run the full suite**

Run: `python3 -m pytest -q`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add README.md docs/setup-guide.md docs/design.md
git commit -m "docs: plugin install path, org memory, recipes, and layout updates"
```

---

### Task 11: Dogfood gate (manual, before any announcement)

End-to-end proof in a scratch project. This task is a checklist executed in a live Claude Code session (the wizard and Workflow tool cannot run under pytest). **Do not announce or version-bump past 0.1.0 until every box is checked.**

- [ ] **Step 1: Scratch project**

```bash
mkdir -p "/private/tmp/claude-501/-Users-brad-Code-AI-Consulting/dogfood" && cd "/private/tmp/claude-501/-Users-brad-Code-AI-Consulting/dogfood"
git init -b main demo && cd demo
mkdir -p src tests docs
printf 'def add(a, b):\n    return a + b\n' > src/calc.py
printf 'from src.calc import add\n\ndef test_add():\n    assert add(1, 2) == 3\n' > tests/test_calc.py
git add -A && git commit -m "chore: seed demo app"
```

- [ ] **Step 2: Install the plugin from the local marketplace**

In a Claude Code session inside `demo/`:

```
/plugin marketplace add "/Users/brad/Code/AI Consulting/agentic-teams-framework"
/plugin install agentic-org@agentic-teams
```

Expected: both succeed; `/org-init` and `/org-update` appear in the skills list and `/team` in commands.

- [ ] **Step 3: Run `/org-init`**

Complete the interview: delivery function only, python stack (`pytest -q`), no CI (accept the warning), recipes = health-check only, real model identifiers for the tiers. Expected: wizard completes, prints the org chart, and reports `validate_org: OK`.

- [ ] **Step 4: Independent validation**

```bash
python3 "$HOME/.claude/plugins/cache"/*/agentic-org/*/scripts/validate_org.py --project-root . 2>/dev/null \
  || python3 "/Users/brad/Code/AI Consulting/agentic-teams-framework/scripts/validate_org.py" --project-root .
```

Expected: `validate_org: OK — 1 team(s) valid` and exit 0. Also spot-check by eye: provenance headers present, PROJECT-CONTEXT blocks filled with demo-specific text, `.gitignore` has the state lines.

- [ ] **Step 5: Dry-run dispatch against the materialized runner**

Read the generated `.claude/teams/dev.yaml`, `context-packs/dev.md`, `model-routing.yaml`, `memory/dev.md`, and the three `org-memory/` files, and assemble them into a `config` object exactly as `/team` step 4 specifies. Then invoke the **project's own** runner in dry-run mode (fixtures present ⇒ no real agents, no state writes):

```
Workflow({
  scriptPath: '.claude/workflows/team-run.js',
  args: {
    team: 'dev', ticket: 'DEMO-1', brief: 'add a subtract function to src/calc.py',
    runId: 'dev-demo-1-20260725T1200', timestamp: '2026-07-25T12:00:00-05:00',
    config: { mission, roster, ownership, routing, pack, memory, orgMemory },
    fixtures: { decompose: { feasible: false, questions: ['dry run — no real planning'], packages: [], testPlan: '' } }
  }
})
```

Expected: returns `status: 'ill-specified'` with `questions: ['dry run — no real planning']` and a `trace` containing one entry labeled `decompose`. Confirm afterwards that `git status` is clean and `.claude/teams/state/` is still empty — dry runs must not write state. This proves the materialized config resolves and the runner's phase wiring survived the org-memory edits.

- [ ] **Step 6: Record and clean up**

Note any friction found (wizard question order, validator false positives, unclear output) as GitHub issues on the framework repo. Remove the scratch dir. Only then: merge the PR, tag `v0.1.0`.

---

## Final: PR

```bash
git push -u origin feature/agentic-org-v1
gh pr create --title "feat: agentic-org v1 — installable plugin with /org-init materializer" \
  --body "Implements docs/superpowers/specs/2026-07-25-agentic-org-plugin-design.md: plugin manifest + self-hosted marketplace, /org-init wizard (curate + customize materialization with provenance), /org-update sync, org-memory layer wired into team-run.js, three workflow recipes, validate_org.py gate, docs. Dogfood checklist in the plan gates the announcement." \
  --base main
```
