#!/usr/bin/env python3
"""Marketplace/manifest checks — every distribution manifest parses, each
plugin's per-host manifests (.claude-plugin / .cursor-plugin / .codex-plugin)
carry the same version and name, the author/owner identity is the canonical
block everywhere, and every marketplace entry points at a real plugin dir.

Globs instead of enumerating so a new plugin or a new host manifest is
covered the day it lands."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUTHOR = {"name": "Yaroslav Krivushenko", "url": "https://github.com/kinnister"}
HOST_DIRS = (".claude-plugin", ".cursor-plugin", ".codex-plugin")

fail = 0


def report(ok: bool, path: Path, msg: str = "") -> None:
    global fail
    rel = path.relative_to(ROOT)
    if ok:
        print("  ok   %s %s" % (rel, msg))
    else:
        print("  FAIL %s %s" % (rel, msg))
        fail = 1


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        report(False, path, "unparseable: %s" % e)
        return None


# (1) every distribution/config JSON parses
plain = [ROOT / "plugins/agentic-os/manifest/dependencies.json"]
plain += sorted((ROOT / "plugins/agentic-os/presets/roles").glob("*.json"))
for f in plain:
    if load(f) is not None:
        report(True, f, "(parses)")

# (2) marketplace manifests: parse + canonical owner + entries resolve
for mp_dir, host_manifest in ((".claude-plugin", ".claude-plugin/plugin.json"),
                              (".cursor-plugin", ".cursor-plugin/plugin.json")):
    mp_path = ROOT / mp_dir / "marketplace.json"
    mp = load(mp_path)
    if mp is None:
        continue
    if mp.get("owner") != AUTHOR:
        report(False, mp_path, "owner != canonical %s" % AUTHOR)
    for entry in mp.get("plugins", []):
        src = ROOT / entry.get("source", "")
        manifest = src / host_manifest
        if not manifest.is_file():
            report(False, mp_path, "entry %r: missing %s" % (entry.get("name"), host_manifest))
        elif entry.get("name") != src.name:
            report(False, mp_path, "entry name %r != source dir %r" % (entry.get("name"), src.name))
    report(True, mp_path, "(owner + %d entries)" % len(mp.get("plugins", [])))

# (3) plugin manifests: parse, name == plugin dir, canonical author,
#     and version identical across all host manifests of the same plugin
for plugin_dir in sorted((ROOT / "plugins").iterdir()):
    if not plugin_dir.is_dir():
        continue
    versions = {}
    for host in HOST_DIRS:
        path = plugin_dir / host / "plugin.json"
        if not path.is_file():
            continue  # codex packaging is optional per plugin
        m = load(path)
        if m is None:
            continue
        ok = True
        if m.get("name") != plugin_dir.name:
            report(False, path, "name %r != plugin dir %r" % (m.get("name"), plugin_dir.name)); ok = False
        if m.get("author") != AUTHOR:
            report(False, path, "author != canonical %s" % AUTHOR); ok = False
        dev = m.get("interface", {}).get("developerName")
        if dev is not None and dev != AUTHOR["name"]:
            report(False, path, "interface.developerName %r != %r" % (dev, AUTHOR["name"])); ok = False
        versions[host] = m.get("version")
        if ok:
            report(True, path, "(v%s)" % m.get("version"))
    if not versions:
        report(False, plugin_dir, "no host manifest found in %s" % (HOST_DIRS,))
    elif len(set(versions.values())) > 1:
        report(False, plugin_dir, "version drift across host manifests: %s" % versions)

sys.exit(fail)
