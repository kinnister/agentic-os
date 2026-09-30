#!/usr/bin/env python3
"""Generate independently installable runtime copies; --check never writes."""
import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PLUGINS = ('agentic-os', 'agentic-sdlc')


def reference(registry):
    lines = ["# Runtime contracts", "", "Generated from runtime/agentic_runtime/registry.json; do not edit.", "",
             "Contract version: `" + registry["contract_version"] + "`.", "",
             "These definitions do not certify host enforcement or implement lifecycle persistence.", ""]
    for section, values in registry.items():
        if section == 'contract_version':
            continue
        lines.extend(["## " + section.replace("_", " ").title(), ""])
        if isinstance(values, dict):
            lines.extend(["| Identifier | Definition |", "|---|---|"])
            for key, value in values.items():
                rendered = json.dumps(value, sort_keys=True).replace('|', '&#124;')
                lines.append("| `" + key + "` | `" + rendered + "` |")
        else:
            lines.extend(["```json", json.dumps(values, indent=2), "```"])
        lines.append("")
    return ("\n".join(lines)).encode()


def expected_files(output_root):
    source = ROOT / 'runtime'
    package = source / 'agentic_runtime'
    files = [source / 'run.py', *sorted(package.glob('*.py')), package / 'registry.json']
    registry = json.loads((package / 'registry.json').read_text())
    template = json.dumps(registry['configuration_template'], indent=2) + '\n'
    template = template.replace('"{{ESCALATE_ON}}"', '[{{ESCALATE_ON}}]').replace('"{{TICKET_INTEGRATION_ENABLED}}"', '{{TICKET_INTEGRATION_ENABLED}}')
    yield output_root / 'plugins/agentic-os/templates/sdlc/config.json.tmpl', template.encode()
    for plugin in PLUGINS:
        target = output_root / 'plugins' / plugin / 'runtime'
        for path in files:
            yield target / path.relative_to(source), path.read_bytes()
        yield target.parent / 'references/runtime-contracts.md', reference(json.loads((package / 'registry.json').read_text()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--output-root', type=pathlib.Path, default=ROOT)
    args = parser.parse_args()
    expected = dict(expected_files(args.output_root))
    drift = []
    for path, content in expected.items():
        if path.is_file() and path.read_bytes() == content:
            continue
        drift.append(str(path.relative_to(args.output_root)))
        if not args.check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    for plugin in PLUGINS:
        target = args.output_root / 'plugins' / plugin / 'runtime'
        for path in target.rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts and path not in expected:
                drift.append(str(path.relative_to(args.output_root)))
                if not args.check:
                    path.unlink()
    if args.check and drift:
        print('Runtime bundle drift:\n' + '\n'.join(drift), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
