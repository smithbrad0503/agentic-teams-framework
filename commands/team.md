# /team Command

Dispatch a team-run or view the team board. The cockpit-side entry point for the
Agentic Teams Framework (design: docs/design.md).

## Usage

```
/team dispatch <team> <ticket> "<brief>" [small|medium|large]
/team status
```

`[small|medium|large]` is a **telemetry label only** — it is recorded on the run so cost
and rounds can be sliced by ticket size. It does not set a token budget, gate budget, or
model effort, and no runner behaviour reads it. Per-gate budgets are the `maxReviewRounds`
/ `maxCiAttempts` / `maxGateRounds` args.

## Dispatch procedure (cockpit executes)

1. **Sync first** (refetch-before-fire; never dispatch from a stale base):
   `git -C "$(git rev-parse --show-toplevel)" fetch origin`
   If the main checkout is on the default branch: also `git pull --ff-only origin <default-branch>`.
   Do NOT switch branches out from under other work.
2. **Generate identity** (workflow scripts cannot call Date):
   `RUN_ID="<team>-$(echo <ticket> | tr 'A-Z' 'a-z')-$(date +%Y%m%dT%H%M)"` and `TS="$(date -Iseconds)"`.
3. **Register the board entry** (seed the file if missing):
   ```bash
   S=.claude/teams/state; mkdir -p $S/runs; [ -f $S/board.json ] || echo '{"runs":[]}' > $S/board.json
   jq --arg id "$RUN_ID" --arg team "<team>" --arg t "<ticket>" --arg ts "$TS" \
     '.runs += [{"id":$id,"team":$team,"ticket":$t,"status":"dispatched","branch":"","pr":"","worktree":"","ts":$ts}]' \
     $S/board.json > $S/board.tmp && mv $S/board.tmp $S/board.json
   printf '%s\n' "{\"ts\":\"$TS\",\"run\":\"$RUN_ID\",\"team\":\"<team>\",\"type\":\"dispatched\",\"ticket\":\"<ticket>\"}" >> $S/events.jsonl
   ```
4. **Resolve config**: Read `.claude/teams/<team>.yaml`, `.claude/teams/model-routing.yaml`,
   the pack file named by `context_pack`, `.claude/teams/memory/<team>.md`, and the
   `.claude/org-memory/` files (decisions.md + architecture.md + lessons.md concatenated
   in that order; "" if the directory is absent). Build
   `config = {mission, roster, ownership, routing, pack, memory, orgMemory}` where `routing` =
   global `defaults` with the team yaml's `routing` overrides merged on top (team wins), plus
   the routing file's top-level `fallback` entry carried through under the key `fallback`
   (a team `routing.fallback` override wins). `fallback` is the route a failed stage's retry
   escalates to — without it the runner uses a conservative built-in default.
5. **Invoke** (background by default):
   `Workflow({name: 'team-run', args: {team, ticket, brief, size, runId: RUN_ID, timestamp: TS, config}})`
6. On completion notification, relay the result to the human: status, PR link, rounds,
   anything blocked. NEVER merge — merge approval is the human's, always.

## Status procedure

```bash
S=.claude/teams/state
jq -r '.runs[] | [.id, .team, .ticket, .status, .pr] | @tsv' $S/board.json 2>/dev/null | column -t
tail -15 $S/events.jsonl 2>/dev/null
git worktree list
```

Render: active runs table, recent events, and ORPHAN flags — any worktree/branch
matching a board run whose status is terminal ({pr-ready, blocked, review-stalemate,
needs-human, ill-specified, done}), or any run branch with no open PR
(`gh pr list --head <branch>` empty) and no board entry. Offer cleanup for orphans;
NEVER auto-delete — an orphan may be a resumable crashed run (crash-resume via
`resumeFromRunId` is a planned enhancement). Never touch branches with open PRs or
uncommitted changes.
