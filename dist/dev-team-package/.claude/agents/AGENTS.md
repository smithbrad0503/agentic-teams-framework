# Agent Registry — Dev Team

The 10 engineering agents this package ships. Each file carries YAML frontmatter
(`name`, `description`, `team`, `tools`, `model`) so Claude Code auto-routes by description;
you can also invoke any agent directly, or let a `team-run`'s decompose stage route to it.

## Roster

```
Lead
  tech-lead        In-code architecture, ADRs, tech-debt, cross-module design; routes to specialists

Specialists (implementation)
  backend-expert   Server-side app code: routing, ORM, validation, auth, caching, background tasks
  frontend-expert  UI framework, components, responsive layout, accessibility, performance
  api-expert       REST/contract design, versioning, tier-based access, request/response schemas
  database-expert  Schema design, safe/reversible migrations, query tuning, indexing

Test / gates (on call to the team)
  qa-tester        Test authoring, mocking, coverage gate, CI configuration
  code-reviewer    Correctness/security review, static analysis, pattern enforcement (REVIEW GATE)
  debug-expert     Root-cause investigation across the stack (invoked on repeat CI failure)

Support
  docs-author      Diff-driven repo-doc updates inside a team-run PR (a stage, not a team member)
  github-expert    CI/CD workflows, PR automation, branch strategy, gh CLI
```

## The `dev` team uses them like this

`.claude/teams/dev.yaml` staffs `lead: tech-lead`, `specialists: [backend-expert,
frontend-expert, api-expert, database-expert]`, `test: qa-tester`. During a run:

- **decompose** → the lead (tech-lead) breaks the ticket into work packages and picks the best
  specialist per package.
- **implement** → the chosen specialist(s) build on the run branch.
- **test** → qa-tester writes/extends tests.
- **docs** → docs-author updates any repo docs the diff invalidates.
- **review gate** → code-reviewer must approve (correctness/security focus).
- **CI gate** → the first CI failure goes back to the lead; a second failure gets debug-expert
  one root-cause pass; a third blocks the run.

## When to invoke a lead vs a specialist directly

- **tech-lead** — a multi-step change needing planning + delegation across specialists.
- **A specialist** — one well-scoped task (e.g. "add a request schema for `/v2/items`" →
  api-expert directly).

## Model tiers

The `model:` frontmatter uses standard Claude Code tier labels. Map them to your org's models.
Stage-level routing inside a run is driven by `.claude/teams/model-routing.yaml`, not by this
per-agent field.
