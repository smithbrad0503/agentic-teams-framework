"""Plugin manifest + marketplace shape, and plugin/tree command sync."""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / ".claude-plugin"
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def test_plugin_manifest_shape() -> None:
    manifest = json.loads((PLUGIN_DIR / "plugin.json").read_text())
    assert manifest["name"] == "agentic-org"
    assert SEMVER.match(manifest["version"]), "version must be plain semver"
    for key in ("description", "license", "repository"):
        assert manifest.get(key), f"plugin.json missing {key}"


def test_runner_version_matches_plugin_version() -> None:
    """The runner stamps RUNNER_VERSION into every run record, and /org-update
    recovers a baseline with `git show v<version>:<source>`. If the runner and the
    manifest disagree, telemetry names a version whose tag holds different code and
    the update path silently diffs against the wrong baseline."""
    manifest = json.loads((PLUGIN_DIR / "plugin.json").read_text())
    runner = (ROOT / ".claude" / "workflows" / "team-run.js").read_text()
    match = re.search(r"const RUNNER_VERSION = '([^']+)'", runner)
    assert match, "team-run.js must declare RUNNER_VERSION"
    assert match.group(1) == manifest["version"], (
        f"RUNNER_VERSION {match.group(1)} != plugin.json {manifest['version']} — bump both together"
    )


def test_declared_version_is_not_behind_the_latest_release_tag() -> None:
    """The manifest version must be >= the highest released tag.

    `/org-init` stamps provenance from `plugin.json`, and `/org-update` recovers a
    baseline with `git show v<version>:<source>`. If a release is tagged without
    bumping the manifest, everything materialized from that tag claims the PREVIOUS
    version — so a later update diffs against a tree that never shipped, and reads
    the newer library's own files as user customizations.

    This is not hypothetical: v0.3.0 was tagged while the manifest still said 0.2.0.
    The sibling test above passed throughout, because it pins the runner to the
    manifest and both were equally stale. Only the tag reveals it.
    """
    import subprocess

    manifest = json.loads((PLUGIN_DIR / "plugin.json").read_text())
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), "tag", "--list", "v*"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - no git available
        pytest.skip("git unavailable")
    if out.returncode != 0:  # pragma: no cover - not a git checkout
        pytest.skip("not a git checkout")
    tags = [t.strip().lstrip("v") for t in out.stdout.splitlines() if SEMVER.match(t.strip().lstrip("v"))]
    if not tags:  # pragma: no cover - shallow clone without tags
        pytest.skip("no release tags fetched (shallow clone?)")

    def parts(v: str) -> tuple[int, int, int]:
        a, b, c = v.split(".")
        return int(a), int(b), int(c)

    highest = max(tags, key=parts)
    assert parts(manifest["version"]) >= parts(highest), (
        f"plugin.json says {manifest['version']} but v{highest} is already tagged — "
        "bump the manifest and RUNNER_VERSION as part of cutting a release, or "
        "everything materialized from that tag stamps the wrong provenance"
    )


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
