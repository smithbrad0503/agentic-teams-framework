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
