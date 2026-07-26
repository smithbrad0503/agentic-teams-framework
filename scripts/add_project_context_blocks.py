#!/usr/bin/env python3
"""Append the PROJECT-CONTEXT block to every library/dist agent missing it.

Idempotent: files that already contain the BEGIN marker are skipped. Processes
both the plugin library (`.claude/agents/`) and the bundled dist subset
(`dist/dev-team-package/.claude/agents/`) so the two never drift on this axis.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT_DIRS = (
    ROOT / ".claude" / "agents",
    ROOT / "dist" / "dev-team-package" / ".claude" / "agents",
)

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
    for agents_dir in AGENT_DIRS:
        if not agents_dir.is_dir():
            continue
        for path in sorted(agents_dir.rglob("*.md")):
            if path.name == "AGENTS.md":
                continue
            text = path.read_text()
            if "PROJECT-CONTEXT:BEGIN" in text:
                continue
            path.write_text(text.rstrip() + "\n" + BLOCK)
            changed.append(str(path.relative_to(ROOT)))
    print(f"updated {len(changed)} agent file(s): {', '.join(changed) or 'none'}")


if __name__ == "__main__":
    main()
