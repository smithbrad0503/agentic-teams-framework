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


def test_plugin_team_command_in_sync() -> None:
    plugin_copy = (ROOT / "commands" / "team.md").read_text()
    tree_copy = (ROOT / ".claude" / "commands" / "team.md").read_text()
    assert plugin_copy == tree_copy, (
        "commands/team.md (plugin) and .claude/commands/team.md (manual-copy tree) "
        "must stay byte-identical — edit both"
    )
