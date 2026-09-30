#!/usr/bin/env bash
# T0 hook unit tests — renders every hook template with default variable values
# into a scratch target-repo layout, then asserts exit codes on canned events.
# Run:  bash tests/t0/run.sh
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
TPL="$REPO/plugins/agentic-os/templates"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

PASS=0
FAIL=0

# check <name> <expected_exit> <stdin-payload|-> <cmd...>
check() {
  local name="$1" expected="$2" payload="$3"; shift 3
  local out rc
  if [ "$payload" = "-" ]; then
    out="$("$@" </dev/null 2>&1)"; rc=$?
  else
    out="$(printf '%s' "$payload" | "$@" 2>&1)"; rc=$?
  fi
  if [ "$rc" -eq "$expected" ]; then
    PASS=$((PASS + 1)); echo "ok   $name"
  else
    FAIL=$((FAIL + 1)); echo "FAIL $name (exit $rc, expected $expected)"; echo "$out" | sed 's/^/     /'
  fi
  LAST_OUT="$out"
}

expect_contains() { # <name> <needle>
  if printf '%s' "$LAST_OUT" | grep -qF "$2"; then
    PASS=$((PASS + 1)); echo "ok   $1"
  else
    FAIL=$((FAIL + 1)); echo "FAIL $1 (output missing '$2')"; printf '%s\n' "$LAST_OUT" | sed 's/^/     /'
  fi
}

render() { # <src.tmpl> <dst> — default-value rendering; fails on leftover {{VAR}}
  python3 - "$1" "$2" <<'PY'
import sys, re
src, dst = sys.argv[1], sys.argv[2]
vals = {
    "SCORECARD_PATH": "docs/audits/instruction-scorecard.json",
    "SCORE_THRESHOLD": "95",
    "AGENTS_CANONICAL_DIR": ".agentic/agents/",
    "DEFAULT_BRANCH": "main",
    "ENV_CHECK_COMMANDS": "true",
    "HUMAN_GATED_COMMANDS": "git push origin main",
    "GUARDED_WRITE_PATHS": "design/VISION.json => /refine-vision",
    "MIGRATIONS_DIR": "supabase/migrations/",
    "MIGRATION_DIFF_COMMAND": "npm run db:diff",
    "AGENTIC_OS_VERSION": "0.0.0-test",
    "LINT_FIX_COMMAND": "true",
    "LINT_CHECK_COMMAND": "grep -q lint-ok",
    "PROJECT_NAME": "t0-fixture",
    "STACK_SUMMARY": "test stack",
    "ROLE_PRESETS_ACTIVE": "developer",
    "HITL_MODE": "gated-autonomous",
    "GATE_COMMANDS": "true",
    "OUTPUT_CONTRACT_SECTIONS": "Summary,Why,Blocking,Non-blocking,Escalate to human",
    # Derived rows the installer fills conditionally; empty is the developer-preset
    # value and the safe representative for this render smoke.
    "QA_GUIDE_ROWS": "",
    "OPS_GUIDE_ROWS": "",
    "SEC_GUIDE_ROWS": "",
    "DATA_GUIDE_ROWS": "",
    "DESIGN_GUIDE_ROWS": "",
    "BA_PO_GUIDE_ROWS": "",
    "GATE_ENTRIES": "",
    # More installer-side conditionals (empty / minimal render-smoke values;
    # the union-dependent variants are exercised by refinstall in run-matrix).
    "CORE_GUIDE_ROWS": "",
    "WRITE_SCOPE_RULE": "Respect your write_scope absolutely.",
    "REVIEW_GATE_SECTION": "",
    "QUALITY_GATES_SECTION": "",
    "ORCHESTRATION_STYLE_RULE": "Multi-step work is orchestrated by the human.",
    "FLEET_INVARIANTS": "1. Write scope is absolute.",
    "ENFORCEMENT_LAYER_ROWS": "",
}
text = open(src, encoding="utf-8").read()
for k, v in vals.items():
    text = text.replace("{{%s}}" % k, v)
left = sorted(set(re.findall(r"\{\{[A-Z_]+\}\}", text)))
if left:
    sys.exit(f"unrendered placeholders in {src}: {left}")
open(dst, "w", encoding="utf-8").write(text)
PY
}

# ---------------------------------------------------------------- scaffold
SCRATCH="$WORK/target"
mkdir -p "$SCRATCH/.claude/hooks" "$SCRATCH/.agentic/agents" "$SCRATCH/docs/audits" \
         "$SCRATCH/.githooks" "$SCRATCH/scripts"

for f in precommit_review_gate.py precompact_checkpoint.py instruction_stale_notice.py session_learnings_notice.py context_monitor.py prompt_scan_guard.py; do
  cp "$TPL/hooks/claude/$f" "$SCRATCH/.claude/hooks/$f"
done
# subagent_gate.py.tmpl renders + compiles here; its behavior cases live in
# tests/t0/run-output-contract.sh.
for t in instruction_gate session_start_bootstrap write_scope_guard human_gated_commands guarded_write_paths migration_notice subagent_gate lint_on_save; do
  render "$TPL/hooks/claude/$t.py.tmpl" "$SCRATCH/.claude/hooks/$t.py"
done
cp "$TPL/githooks/pre-commit" "$SCRATCH/.githooks/pre-commit"
cp "$TPL/scripts/install-git-hooks.sh" "$SCRATCH/scripts/install-git-hooks.sh"

# governance templates render clean (content checked by instruction audit, not here).
# Via `check` so a leftover placeholder — the exact regression a new {{VAR}} in one
# of these templates causes — fails the suite instead of being swallowed.
for g in CLAUDE.section.md AGENTS.md PATTERNS.md; do
  check "governance $g renders clean" 0 - render "$TPL/governance/$g.tmpl" "$WORK/$g"
done

echo "-- compile + fragment"
check "py_compile all hooks" 0 - python3 -m py_compile "$SCRATCH"/.claude/hooks/*.py
check "settings-fragment is valid JSON" 0 - python3 -c "import json;json.load(open('$TPL/hooks/settings-fragment.json.tmpl'))"

git -C "$SCRATCH" init -q -b main
git -C "$SCRATCH" config user.email t0@test && git -C "$SCRATCH" config user.name t0
echo base > "$SCRATCH/base.txt"
git -C "$SCRATCH" add base.txt && git -C "$SCRATCH" -c commit.gpgsign=false commit -qm init

GATE="$SCRATCH/.claude/hooks/precommit_review_gate.py"
run_in() { (cd "$SCRATCH" && "$@"); }
ev_bash() { printf '{"tool_name":"Bash","tool_input":{"command":"%s"}}' "$1"; }
ev_file() { printf '{"tool_name":"Write","tool_input":{"file_path":"%s"}}' "$1"; }

echo "-- precommit_review_gate"
check "gate: non-commit command allowed" 0 "$(ev_bash 'git status')" run_in python3 "$GATE"
# fail-open guard: `tool_input: null` used to crash (exit 1 = non-blocking), which
# would admit an unreviewed commit. No command to gate → clean allow, never exit 1.
check "gate: null tool_input not exit-1" 0 '{"tool_name":"Bash","tool_input":null}' run_in python3 "$GATE"
echo change > "$SCRATCH/f.txt"; git -C "$SCRATCH" add f.txt
check "gate: unreviewed commit blocked" 2 "$(ev_bash 'git commit -m x')" run_in python3 "$GATE"
check "gate: auto-stage (-am) refused" 2 "$(ev_bash 'git commit -am x')" run_in python3 "$GATE"
check "precommit mode: unreviewed blocked" 1 - run_in python3 "$GATE" precommit
check "approve stamps staged diff" 0 - run_in python3 "$GATE" approve
check "gate: approved commit allowed" 0 "$(ev_bash 'git commit -m x')" run_in python3 "$GATE"
check "precommit mode: approved allowed" 0 - run_in python3 "$GATE" precommit
echo more >> "$SCRATCH/f.txt"; git -C "$SCRATCH" add f.txt
check "gate: restage invalidates stamp" 2 "$(ev_bash 'git commit -m x')" run_in python3 "$GATE"
check "precommit mode: SKIP_REVIEW=1 bypass" 0 - run_in env SKIP_REVIEW=1 python3 "$GATE" precommit
check "gate: [skip-review] bypass" 0 "$(ev_bash 'git commit -m merge-x-[skip-review]')" run_in python3 "$GATE"
git -C "$SCRATCH" reset -q

echo "-- human_gated_commands"
HG="$SCRATCH/.claude/hooks/human_gated_commands.py"
check "human-gated command blocked" 2 "$(ev_bash 'git push origin main')" run_in python3 "$HG"
expect_contains "  ...with escalation pointer" "escalation-policy.md"
check "ordinary command allowed" 0 "$(ev_bash 'git push origin feature/x')" run_in python3 "$HG"
# fail-open guard: a malformed `tool_input: null` used to crash (AttributeError →
# exit 1), which PreToolUse treats as non-blocking — the gated command slipped
# through. Must be a clean allow now, never exit 1.
check "human-gated null tool_input not exit-1" 0 '{"tool_name":"Bash","tool_input":null}' run_in python3 "$HG"
# fail-closed: a non-string command can't be evaluated — block, do not exit 1.
check "human-gated non-string command fails closed" 2 '{"tool_name":"Bash","tool_input":{"command":123}}' run_in python3 "$HG"

echo "-- guarded_write_paths"
GW="$SCRATCH/.claude/hooks/guarded_write_paths.py"
check "guarded path write blocked" 2 "$(ev_file 'design/VISION.json')" run_in python3 "$GW"
expect_contains "  ...names the allowed flow" "/refine-vision"
check "unguarded path write allowed" 0 "$(ev_file 'app/page.tsx')" run_in python3 "$GW"
check "guarded null tool_input not exit-1" 0 '{"tool_name":"Write","tool_input":null}' run_in python3 "$GW"
check "guarded non-string path fails closed" 2 '{"tool_name":"Write","tool_input":{"file_path":123}}' run_in python3 "$GW"

echo "-- write_scope_guard"
WS="$SCRATCH/.claude/hooks/write_scope_guard.py"
printf -- '---\nname: scoped\nwrite_scope:\n  - app/\n---\nbody\n' > "$SCRATCH/.agentic/agents/scoped.md"
check "no lock: open mode" 0 "$(ev_file "$SCRATCH/lib/x.ts")" run_in python3 "$WS" block
mkdir -p "$SCRATCH/.agentic/state"
printf '{"agent":"scoped"}' > "$SCRATCH/.agentic/state/active-agent.json"
check "locked: in-scope write allowed" 0 "$(ev_file "$SCRATCH/app/x.ts")" run_in python3 "$WS" block
check "locked: out-of-scope write blocked" 2 "$(ev_file "$SCRATCH/lib/x.ts")" run_in python3 "$WS" block
expect_contains "  ...names the lane" "outside its lane"
check "locked: sibling-prefix dir blocked (app/ vs app-legacy/)" 2 "$(ev_file "$SCRATCH/app-legacy/x.ts")" run_in python3 "$WS" block
printf -- '---\nname: scoped\nwrite_scope:\n  - app/\nforbidden_paths:\n  - app/secrets/\n---\nbody\n' > "$SCRATCH/.agentic/agents/scoped.md"
check "locked: forbidden path blocked even in scope" 2 "$(ev_file "$SCRATCH/app/secrets/k.ts")" run_in python3 "$WS" block
printf -- '---\nname: scoped\nreadonly: true\nwrite_scope: []\nforbidden_paths:\n  - "**"\n---\nbody\n' > "$SCRATCH/.agentic/agents/scoped.md"
check "locked: read-only Bash blocked" 2 '{"tool_name":"Bash","tool_input":{"command":"touch app/x.ts"}}' run_in python3 "$WS" block
printf -- '---\nname: scoped\nreadonly: true\nwrite_scope: []\n---\nbody\n' > "$SCRATCH/.agentic/agents/scoped.md"
check "locked: read-only Write blocked without deny glob" 2 "$(ev_file "$SCRATCH/app/x.ts")" run_in python3 "$WS" block
printf -- '---\nname: scoped\nwrite_scope: []\nforbidden_paths:\n  - "**"\n---\nbody\n' > "$SCRATCH/.agentic/agents/scoped.md"
check "locked: quoted glob forbidden path blocked" 2 "$(ev_file "$SCRATCH/app/x.ts")" run_in python3 "$WS" block
# fail-closed (block mode, lock active): a non-string file_path can't be resolved —
# block, never exit 1. warn mode stays advisory (exit 0) on the same input.
check "locked: non-string path fails closed (block)" 2 '{"tool_name":"Write","tool_input":{"file_path":123}}' run_in python3 "$WS" block
check "locked: non-string path advisory (warn)" 0 '{"tool_name":"Write","tool_input":{"file_path":123}}' run_in python3 "$WS" warn
check "warn mode never blocks" 0 "$(ev_file "$SCRATCH/lib/x.ts")" run_in python3 "$WS" warn
# null tool_input under an active lock: no path to evaluate → open (exit 0), never exit 1.
check "locked: null tool_input not exit-1 (block)" 0 '{"tool_name":"Write","tool_input":null}' run_in python3 "$WS" block
rm "$SCRATCH/.agentic/state/active-agent.json"
printf '{"agent":}' > "$SCRATCH/.agentic/state/active-agent.json"
check "broken managed state fails closed" 2 "$(ev_file "$SCRATCH/lib/x.ts")" run_in python3 "$WS" block
rm "$SCRATCH/.agentic/state/active-agent.json"

echo "-- instruction_gate"
IG="$SCRATCH/.claude/hooks/instruction_gate.py"
printf -- '---\nname: foo\nwrite_scope:\n  - app/\n---\nbody\n' > "$SCRATCH/.agentic/agents/foo.md"
ev_spawn() { printf '{"subagent_type":"%s"}' "$1"; }
check "ungoverned agent allowed" 0 "$(ev_spawn 'not-in-fleet')" run_in python3 "$IG"
check "governed + no scorecard blocked" 2 "$(ev_spawn 'foo')" run_in python3 "$IG"
SHA=$(python3 -c "import hashlib;print(hashlib.sha256(open('$SCRATCH/.agentic/agents/foo.md','rb').read()).hexdigest())")
printf '{"files":{".agentic/agents/foo.md":{"content_sha256":"%s","composite_score":100}}}' "$SHA" \
  > "$SCRATCH/docs/audits/instruction-scorecard.json"
check "governed + graded 100 allowed" 0 "$(ev_spawn 'foo')" run_in python3 "$IG"
printf '{"files":{".agentic/agents/foo.md":{"content_sha256":"deadbeef","composite_score":100}}}' \
  > "$SCRATCH/docs/audits/instruction-scorecard.json"
check "stale content blocked" 2 "$(ev_spawn 'foo')" run_in python3 "$IG"
printf '{"files":{".agentic/agents/foo.md":{"content_sha256":"%s","composite_score":85,"gate_threshold":80}}}' "$SHA" \
  > "$SCRATCH/docs/audits/instruction-scorecard.json"
check "per-agent gate_threshold override" 0 "$(ev_spawn 'foo')" run_in python3 "$IG"
printf -- '---\nname: instruction-auditor\n---\nbody\n' > "$SCRATCH/.agentic/agents/instruction-auditor.md"
check "instruction-auditor exempt" 0 "$(ev_spawn 'instruction-auditor')" run_in python3 "$IG"
check "no agent-name key: loud allow" 0 '{"unrelated":"x"}' run_in python3 "$IG"

echo "-- migration_notice + instruction_stale_notice + precompact + session bootstrap"
MN="$SCRATCH/.claude/hooks/migration_notice.py"
check "migration edit noticed" 0 "$(ev_file 'supabase/migrations/1_x.sql')" run_in python3 "$MN"
expect_contains "  ...suggests diff command" "npm run db:diff"
check "non-migration edit silent" 0 "$(ev_file 'app/page.tsx')" run_in python3 "$MN"
if [ -n "$LAST_OUT" ]; then FAIL=$((FAIL+1)); echo "FAIL migration_notice not silent"; else PASS=$((PASS+1)); echo "ok     ...and silent"; fi

SN="$SCRATCH/.claude/hooks/instruction_stale_notice.py"
check "stale notice on ungraded governed file" 0 "$(ev_file '.agentic/guides/standards/x.md')" run_in sh -c "mkdir -p .agentic/guides/standards && echo hi > .agentic/guides/standards/x.md && python3 $SN"
expect_contains "  ...advisory names the file" "x.md"
check "stale notice silent on ungoverned file" 0 "$(ev_file 'src/x.ts')" run_in python3 "$SN"

check "precompact checkpoint exits 0" 0 '{"trigger":"manual"}' run_in python3 "$SCRATCH/.claude/hooks/precompact_checkpoint.py"
[ -f "$SCRATCH/.claude/checkpoints/last-compaction.md" ] && { PASS=$((PASS+1)); echo "ok     ...checkpoint written"; } || { FAIL=$((FAIL+1)); echo "FAIL checkpoint file missing"; }

check "session bootstrap exits 0 (no origin)" 0 '{}' run_in python3 "$SCRATCH/.claude/hooks/session_start_bootstrap.py"

echo "-- prompt_scan_guard"
PS="$SCRATCH/.claude/hooks/prompt_scan_guard.py"
ev_prompt() { python3 -c 'import json,sys;print(json.dumps({"session_id":"t0-ps","prompt":sys.argv[1]}))' "$1"; }
check "scan: clean prompt silent" 0 "$(ev_prompt 'please refactor the login page')" run_in python3 "$PS"
if [ -z "$LAST_OUT" ]; then PASS=$((PASS+1)); echo "ok     ...and silent"; else FAIL=$((FAIL+1)); echo "FAIL scan spoke on clean prompt"; fi
PEM_PROMPT="use this -----BEGIN RSA PRIVATE KEY----- MIIEow"
check "scan: private key warns by default" 0 "$(ev_prompt "$PEM_PROMPT")" run_in python3 "$PS"
expect_contains "  ...advisory names the class" "private_key"
check "scan: private key blocks in block mode" 2 "$(ev_prompt "$PEM_PROMPT")" run_in env AGENTIC_PROMPT_SCAN_MODE=block python3 "$PS"
expect_contains "  ...block names remediation" "env var"
check "scan: luhn card blocks in block mode" 2 "$(ev_prompt 'charge card 4111 1111 1111 1111 today')" run_in env AGENTIC_PROMPT_SCAN_MODE=block python3 "$PS"
check "scan: non-luhn digits pass" 0 "$(ev_prompt 'order id 1234 5678 9012 3456 shipped')" run_in env AGENTIC_PROMPT_SCAN_MODE=block python3 "$PS"
check "scan: placeholder assignment passes" 0 "$(ev_prompt 'set api_key = <YOUR_KEY_HERE> in the env')" run_in env AGENTIC_PROMPT_SCAN_MODE=block python3 "$PS"
check "scan: 'token is expired' safe words pass" 0 "$(ev_prompt 'the token is expired, refresh it')" run_in env AGENTIC_PROMPT_SCAN_MODE=block python3 "$PS"
check "scan: audit mode silent" 0 "$(ev_prompt "$PEM_PROMPT")" run_in env AGENTIC_PROMPT_SCAN_MODE=audit python3 "$PS"
if [ -z "$LAST_OUT" ]; then PASS=$((PASS+1)); echo "ok     ...and silent"; else FAIL=$((FAIL+1)); echo "FAIL audit mode not silent"; fi
[ -f "$SCRATCH/.agentic/state/prompt-scan-audit.jsonl" ] && { PASS=$((PASS+1)); echo "ok     ...audit trail written (masked)"; } || { FAIL=$((FAIL+1)); echo "FAIL audit trail missing"; }
check "scan: malformed stdin not exit-1" 0 'not-json' run_in python3 "$PS"

echo "-- context_monitor"
CM="$SCRATCH/.claude/hooks/context_monitor.py"
CT="$WORK/t0-cm-transcript.jsonl"
ev_cm() { printf '{"session_id":"t0-cm-%s-%s","transcript_path":"%s"}' "$$" "$1" "$CT"; }
usage_line() { printf '{"message":{"usage":{"input_tokens":%s,"cache_read_input_tokens":%s,"cache_creation_input_tokens":0}}}\n' "$1" "$2"; }
usage_line 10000 10000 > "$CT"   # 10% — below warn
check "context: low usage silent" 0 "$(ev_cm low)" run_in env AGENTIC_CONTEXT_CHECK_INTERVAL=1 python3 "$CM"
if [ -z "$LAST_OUT" ]; then PASS=$((PASS+1)); echo "ok     ...and silent"; else FAIL=$((FAIL+1)); echo "FAIL context monitor spoke below warn"; fi
usage_line 100000 40000 >> "$CT"   # 70% — warn band
check "context: warn threshold announced" 0 "$(ev_cm warn)" run_in env AGENTIC_CONTEXT_CHECK_INTERVAL=1 python3 "$CM"
expect_contains "  ...names the monitor" "context-monitor"
check "context: same level not re-announced" 0 "$(ev_cm warn)" run_in env AGENTIC_CONTEXT_CHECK_INTERVAL=1 python3 "$CM"
if [ -z "$LAST_OUT" ]; then PASS=$((PASS+1)); echo "ok     ...no repeat nag"; else FAIL=$((FAIL+1)); echo "FAIL context monitor nagged twice at same level"; fi
usage_line 150000 10000 >> "$CT"   # 80% — urgent band, same session escalates
check "context: urgent escalation announced" 0 "$(ev_cm warn)" run_in env AGENTIC_CONTEXT_CHECK_INTERVAL=1 python3 "$CM"
expect_contains "  ...urgent names the seam" "URGENT"
check "context: sampling skips off-interval calls" 0 "$(ev_cm sampled)" run_in env AGENTIC_CONTEXT_CHECK_INTERVAL=5 python3 "$CM"
if [ -z "$LAST_OUT" ]; then PASS=$((PASS+1)); echo "ok     ...and silent on call 1 of 5"; else FAIL=$((FAIL+1)); echo "FAIL sampling did not skip"; fi
check "context: malformed stdin not exit-1" 0 'not-json' run_in python3 "$CM"
check "context: disabled via env" 0 "$(ev_cm off)" run_in env AGENTIC_CONTEXT_MONITOR_DISABLED=1 python3 "$CM"

echo "-- lint_on_save"
LN="$SCRATCH/.claude/hooks/lint_on_save.py"
printf 'lint-ok\n' > "$SCRATCH/clean.ts"
check "lint: clean file passes" 0 "$(ev_file "$SCRATCH/clean.ts")" run_in python3 "$LN"
printf 'needs-work\n' > "$SCRATCH/dirty.ts"
check "lint: remaining errors exit 2 (same-turn feedback)" 2 "$(ev_file "$SCRATCH/dirty.ts")" run_in python3 "$LN"
expect_contains "  ...names the file and asks for same-turn fix" "lint-on-save"
printf 'prose\n' > "$SCRATCH/notes.txt"
check "lint: non-source file silent" 0 "$(ev_file "$SCRATCH/notes.txt")" run_in python3 "$LN"
check "lint: missing file silent" 0 "$(ev_file "$SCRATCH/gone.ts")" run_in python3 "$LN"
check "lint: malformed stdin not exit-1" 0 'not-json' run_in python3 "$LN"
check "lint: disabled via env" 0 "$(ev_file "$SCRATCH/dirty.ts")" run_in env AGENTIC_LINT_ON_SAVE_DISABLED=1 python3 "$LN"
# fail-open when the configured tool does not exist on PATH
sed 's/grep -q lint-ok/agentic-no-such-tool-xyz --check/' "$LN" > "$SCRATCH/.claude/hooks/lint_missing_tool.py"
check "lint: missing tool fails open" 0 "$(ev_file "$SCRATCH/dirty.ts")" run_in python3 "$SCRATCH/.claude/hooks/lint_missing_tool.py"
# fail-open when a wrapper (npx-style) exists but the real linter is broken:
# non-zero exit + tool-failure signature must NOT read as lint errors.
printf '#!/bin/sh\necho "Oops! Something went wrong! :("\necho "could not determine executable to run"\nexit 1\n' > "$SCRATCH/fake-npx.sh"
chmod +x "$SCRATCH/fake-npx.sh"
sed "s|grep -q lint-ok|$SCRATCH/fake-npx.sh|" "$LN" > "$SCRATCH/.claude/hooks/lint_broken_tool.py"
check "lint: broken wrapper tool fails open" 0 "$(ev_file "$SCRATCH/dirty.ts")" run_in python3 "$SCRATCH/.claude/hooks/lint_broken_tool.py"
# exit >= 126 (not executable / not found through a shell wrapper) fails open too
printf '#!/bin/sh\nexit 127\n' > "$SCRATCH/exit127.sh"; chmod +x "$SCRATCH/exit127.sh"
sed "s|grep -q lint-ok|$SCRATCH/exit127.sh|" "$LN" > "$SCRATCH/.claude/hooks/lint_127_tool.py"
check "lint: exit-127 tool fails open" 0 "$(ev_file "$SCRATCH/dirty.ts")" run_in python3 "$SCRATCH/.claude/hooks/lint_127_tool.py"

echo "-- session_learnings_notice"
SL="$SCRATCH/.claude/hooks/session_learnings_notice.py"
TRANSCRIPT="$WORK/t0-transcript.jsonl"
# session_id carries $$ — the hook keeps per-session state in $TMPDIR, and a
# reused id would make the first "noticed" case start pre-silenced on re-runs.
ev_stop() { printf '{"session_id":"t0-%s-%s","transcript_path":"%s","stop_hook_active":false}' "$$" "$1" "$TRANSCRIPT"; }
printf '%s\n' '{"message":{"role":"user","content":[{"type":"text","text":"please add a button to the page"}]}}' > "$TRANSCRIPT"
check "learnings: clean transcript silent" 0 "$(ev_stop clean)" run_in python3 "$SL"
if [ -z "$LAST_OUT" ]; then PASS=$((PASS+1)); echo "ok     ...and silent"; else FAIL=$((FAIL+1)); echo "FAIL learnings not silent on clean transcript"; fi
printf '%s\n' '{"message":{"role":"user","content":[{"type":"text","text":"that is wrong, you forgot the tests. did you run them?"}]}}' >> "$TRANSCRIPT"
check "learnings: correction signals noticed" 0 "$(ev_stop sig)" run_in python3 "$SL"
expect_contains "  ...advisory points at the memory store" "session-learnings"
check "learnings: same signals, repeat Stop silent" 0 "$(ev_stop sig)" run_in python3 "$SL"
if [ -z "$LAST_OUT" ]; then PASS=$((PASS+1)); echo "ok     ...no repeat nag"; else FAIL=$((FAIL+1)); echo "FAIL learnings nagged twice for the same signals"; fi
check "learnings: stop_hook_active silent" 0 '{"stop_hook_active":true}' run_in python3 "$SL"
check "learnings: malformed stdin not exit-1" 0 'not-json' run_in python3 "$SL"

echo "-- git layer (chaining installer)"
REPO2="$WORK/target2"
mkdir -p "$REPO2/.claude/hooks" "$REPO2/scripts" "$REPO2/.githooks"
cp "$TPL/hooks/claude/precommit_review_gate.py" "$REPO2/.claude/hooks/"
cp "$TPL/githooks/pre-commit" "$REPO2/.githooks/pre-commit"
cp "$TPL/scripts/install-git-hooks.sh" "$REPO2/scripts/install-git-hooks.sh"
git -C "$REPO2" init -q -b main
git -C "$REPO2" config user.email t0@test && git -C "$REPO2" config user.name t0
# pre-existing foreign hook that must be preserved and chained
printf '#!/bin/sh\ntouch chained-ran\nexit 0\n' > "$REPO2/.git/hooks/pre-commit"
chmod +x "$REPO2/.git/hooks/pre-commit"
check "installer runs" 0 - sh -c "cd '$REPO2' && bash scripts/install-git-hooks.sh"
[ -x "$REPO2/.git/hooks/pre-commit.local" ] && { PASS=$((PASS+1)); echo "ok     ...foreign hook preserved as .local"; } || { FAIL=$((FAIL+1)); echo "FAIL foreign hook not preserved"; }
grep -q "agentic-os:" "$REPO2/.git/hooks/pre-commit" && { PASS=$((PASS+1)); echo "ok     ...our hook installed"; } || { FAIL=$((FAIL+1)); echo "FAIL our hook not installed"; }
check "installer idempotent (re-run)" 0 - sh -c "cd '$REPO2' && bash scripts/install-git-hooks.sh"
[ -f "$REPO2/.git/hooks/pre-commit.local.local" ] && { FAIL=$((FAIL+1)); echo "FAIL double-chained .local.local"; } || { PASS=$((PASS+1)); echo "ok     ...no double-chaining"; }

echo x > "$REPO2/a.txt" && git -C "$REPO2" add a.txt
check "native hook blocks unreviewed commit" 1 - sh -c "cd '$REPO2' && git -c commit.gpgsign=false commit -qm x"
( cd "$REPO2" && python3 .claude/hooks/precommit_review_gate.py approve >/dev/null )
check "native hook passes approved commit" 0 - sh -c "cd '$REPO2' && git -c commit.gpgsign=false commit -qm x"
[ -f "$REPO2/chained-ran" ] && { PASS=$((PASS+1)); echo "ok     ...chained .local hook ran"; } || { FAIL=$((FAIL+1)); echo "FAIL chained hook did not run"; }

echo
echo "T0: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
