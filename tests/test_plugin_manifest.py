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
