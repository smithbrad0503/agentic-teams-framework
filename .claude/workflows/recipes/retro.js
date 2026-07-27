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
// Shared recipe contract: every recipe returns `verdict`, and INCOMPLETE is reserved
// across all of them for "an agent died, so this is not a complete judgement". This
// recipe has a single agent and nothing to partially lose — it either wrote the retro
// or it did not — so INCOMPLETE and the error path are the same event here.
if (!res) return { timestamp: A.timestamp, verdict: 'INCOMPLETE', error: 'retro: retro agent returned no report' }
log(`retro: wrote ${res.path}`)
return { timestamp: A.timestamp, verdict: 'WRITTEN', ...res }
