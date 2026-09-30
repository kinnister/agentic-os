#!/usr/bin/env bash
# End-to-end Cursor install smoke test.
#
# 1. Validates Cursor plugin packaging in the agentic-os repo.
# 2. Creates (or recreates) a fresh fixture repo under git/test/.
# 3. Runs the deterministic scaffold (refinstall.py) for the explicit ba-po
#    role — the same Phase 4 output /agentic-init --presets ba-po would produce.
# 4. Asserts the scaffold matches the T1 fresh-install invariants.
#
# Usage:
#   bash tests/cursor/run-cursor-e2e.sh
#   TARGET=/path/to/repo bash tests/cursor/run-cursor-e2e.sh
set -euo pipefail

ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
PLUGIN="$ROOT/plugins/agentic-os"
DEFAULT_TARGET="${TARGET:-$ROOT/../test/agentic-os-cursor-fresh-install}"
# mkdir -p first: if $(dirname "$DEFAULT_TARGET") doesn't exist (true on every
# fresh clone and every CI runner), a bare `cd` fails here but does NOT trip
# set -e — the assignment's exit status comes from the trailing $(basename)
# command substitution, which still succeeds. Without this line TARGET
# silently collapses to "/$(basename "$DEFAULT_TARGET")", and make-fresh.sh
# immediately does `rm -rf "$TARGET"` on it.
mkdir -p "$(dirname "$DEFAULT_TARGET")"
TARGET="$(cd "$(dirname "$DEFAULT_TARGET")" && pwd)/$(basename "$DEFAULT_TARGET")"

PASS=0
FAIL=0
ok()   { echo "ok   $1"; PASS=$((PASS + 1)); }
bad()  { echo "FAIL $1"; FAIL=$((FAIL + 1)); }
assert() { if eval "$2"; then ok "$1"; else bad "$1"; fi; }

echo "== Cursor packaging =="
python3 "$ROOT/tests/cursor/check-cursor-packaging.py"

echo "== Fresh fixture at $TARGET =="
bash "$ROOT/tests/fixtures/make-fresh.sh" "$TARGET" >/dev/null
ok "fixture created"

echo "== Scaffold (agentic-init Phase 4 reference) =="
python3 "$ROOT/tests/lib/refinstall.py" "$PLUGIN" "$TARGET" \
  --presets ba-po --mcp-state without-mcp >/dev/null
ok "refinstall completed"
if test -f "$TARGET/scripts/install-git-hooks.sh"; then
  ( cd "$TARGET" && bash scripts/install-git-hooks.sh >/dev/null )
  ok "git hooks installed"
else
  ok "git hooks not installed for ba-po-only role"
fi

echo "== Post-install assertions =="
assert "hooks py_compile" "python3 -m py_compile '$TARGET'/.claude/hooks/*.py"
assert "settings valid JSON" "python3 -c 'import json;json.load(open(\"$TARGET/.claude/settings.json\"))'"
assert "agentic layer present" "test -d '$TARGET/.agentic/agents'"
assert "scorecard present" "test -f '$TARGET/docs/audits/instruction-scorecard.json'"
assert "no unresolved placeholders" "! grep -rlF '{{' '$TARGET/.claude' '$TARGET/.agentic' '$TARGET/AGENTS.md' '$TARGET/PATTERNS.md' '$TARGET/CLAUDE.md' 2>/dev/null | grep -q ."
assert "ba-po dispatcher present" "test -f '$TARGET/.agentic/agents/dispatcher.md'"
assert "ba-po operating guide present" "test -f '$TARGET/.agentic/guides/standards/ba-po-operating-model.md'"
assert "ba-po has no developer agents" "! test -e '$TARGET/.agentic/agents/security-reviewer.md' && ! test -e '$TARGET/.agentic/agents/blind-code-reviewer.md'"
assert "MCP fallback guide present" "grep -q 'without MCP' '$TARGET/.agentic/guides/standards/mcp-onboarding.md'"
assert "no-adapter status is honest" "grep -A2 -q '\*\*Status\*\*: not configured' '$TARGET/.agentic/guides/project.md'"

python3 "$ROOT/tests/lib/check-registry.py" "$TARGET" && ok "agent-registry intact" || bad "agent-registry intact"
python3 "$ROOT/tests/lib/check-hooks-import.py" "$TARGET" && ok "hooks import cleanly" || bad "hooks import cleanly"

RESULT_FILE="$TARGET/CURSOR-E2E-RESULT.md"
cat > "$RESULT_FILE" <<EOF
# Cursor E2E install smoke result

- **Target repo**: \`$TARGET\`
- **Plugin root**: \`$PLUGIN\`
- **Marketplace**: \`$ROOT/.cursor-plugin/marketplace.json\`
- **Assertions**: ${PASS} passed, ${FAIL} failed

## Manual Cursor steps (after marketplace merge)

1. Cursor → Settings → Plugins → Add marketplace → \`$ROOT\` (local clone) or \`https://github.com/kinnister/agentic-os.git\`
2. Install **agentic-os** and **agentic-sdlc** from the \`agentic-os\` marketplace
3. Restart the session
4. Open this repo in Cursor and run \`/agentic-init --presets ba-po\`

This automated run validated packaging + deterministic scaffold only.
EOF
ok "wrote $RESULT_FILE"

echo ""
if [[ "$FAIL" -eq 0 ]]; then
  echo "CURSOR-E2E: $PASS passed, 0 failed"
  exit 0
fi
echo "CURSOR-E2E: $PASS passed, $FAIL failed"
exit 1
