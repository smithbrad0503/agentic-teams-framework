# Agent Registry

The specialized agents available to the Agentic Teams Framework. Every file in this
directory carries YAML frontmatter (`name`, `description`, `team`, `tools`, `model`)
so the Claude Code harness auto-routes by description — it matches a request to the
agent whose `description` contains the right triggers. You can also invoke any agent
directly for a focused task, or let a team-run's decompose stage route to it.

## Three-tier hierarchy

Claude Code is flat under the hood; hierarchy is enforced by `tools` access and by
`description` cross-references (the do / do-NOT-use-for lines).

- **Team leads** (`team: lead`) — `orchestrator`, `tech-lead`, `product-manager`.
  These carry the `Agent` tool, so when invoked they can spawn their own specialists.
  Use a lead when a task needs strategy + delegation across several specialists.
- **Specialists** (`team: <name>`) — implementation/execution roles. No `Agent` tool.
  Invoke directly for a focused task, or let a lead route to them.
- **Top-level coordinator** — `orchestrator` is the only agent that crosses team
  boundaries (effectively the AI CTO).

## Model tiers (placeholders — map to your org's models)

The `model:` frontmatter uses standard Claude Code tiers. Treat them as tier labels
and map to whatever models your setup exposes:

- **Strongest tier** — `orchestrator`, `tech-lead`, `product-manager` (strategy);
  `code-reviewer`, `security-expert`, `legal-expert` (high-stakes correctness / gates
  that must not miss things).
- **Mid tier** — the remaining specialists (implementation, infra, integrations, content).

Stage-level routing inside a team-run is driven separately by
`.claude/teams/model-routing.yaml`, not by this per-agent `model:` field.

## The org (roster by team)

```
Coordination (leads)
  orchestrator        Cross-team AI-CTO: decompose initiatives, delegate, run gates
  tech-lead           In-code architecture, ADRs, tech-debt, cross-module design
  product-manager     Product strategy, roadmap, RICE, user stories, tiering

Engineering (delivery)
  software-engineer   Generalist implementer when no specialist fits: games, CLIs, libraries
  backend-expert      Server-side app code: routing, ORM, validation, auth, caching
  frontend-expert     UI framework, components, responsive layout, a11y, perf
  api-expert          REST/contract design, versioning, tier-based access
  database-expert     Schema design, migrations (safe/reversible), query tuning
  qa-tester           Test authoring, mocking, coverage gate, CI config
  code-reviewer       Correctness/security review, static analysis, pattern enforcement (GATE)
  debug-expert        Root-cause investigation across the stack (on call to every team)
  docs-author         Diff-driven repo-doc updates inside a team-run PR (stage, not member)
  github-expert       CI/CD workflows, PR automation, branch strategy, gh CLI

Platform / SecOps
  cloud-infra-expert  Infra-as-code, containers/serverless, managed DB/cache, secrets, IAM
  sre                 Incident response, monitoring/alerting, scaling, DR, uptime
  security-expert     AuthN, hashing, rate limiting, OWASP, secrets, security review (GATE)

Advisory (document output)
  ux-designer         User flows, wireframes, design tokens/specs, WCAG accessibility
  analytics-expert    Event tracking, funnels, cohorts, churn, A/B tests
  finops-expert       SaaS KPIs (MRR/LTV/CAC), subscription lifecycle, unit economics
  marketing-expert    Positioning, content strategy, GTM/launch, CAC (legal-expert gates claims)
  copywriter          Blog/product/email copy, explainers, SEO, brand voice
  legal-expert        ToS/privacy, GDPR/CCPA, FTC claims, contracts (compliance GATE)

Optional (require an MCP connection — see optional/)
  notion-expert       Notion pages/databases/docs structure
  slack-expert        Slack messaging, webhooks, interactive components
```

## When to invoke a lead vs a specialist

- **Lead** — a multi-step initiative needing planning + delegation
  (e.g. "design the ingestion architecture" → tech-lead, who routes to the specialists).
- **Specialist** — one well-scoped task (e.g. "add a request schema for `/v2/items`" →
  api-expert directly).

## How teams use this roster

A `.claude/teams/<team>.yaml` names a `lead`, `specialists`, and a `test` agent from
this directory. `ls .claude/teams/*.yaml` is the live org chart; this registry is the
directory of who's available to staff those teams. The team-run's decompose stage picks
the best `agentType` per work package from the staffed roster; the review and CI gates
always use `code-reviewer` and (on repeat CI failure) `debug-expert`, regardless of team.

## Adding a new agent

1. Create `<name>.md` here with frontmatter (`name`, `description`, `team`, `tools`, `model`).
   The `description` is load-bearing — put the do / do-NOT-use-for triggers in it.
2. Reference it from a team yaml's roster (its file must exist or the schema test fails).
3. Keep it generic and pointer-driven; project specifics belong in context packs, not agents.
