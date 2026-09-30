#!/usr/bin/env bash
#
# qa-assemble-meta.sh — build a run's final meta.json from its intermediates.
#
# Reads up to four per-run JSON artifacts (all optional) from <output_dir> and
# folds them into a single meta.json summary. Every field read is tolerant: a
# missing, unreadable, or malformed input never fails the run — the field falls
# back to its documented default instead.
#
# Usage: qa-assemble-meta.sh <output_dir>
#
# Inputs (under <output_dir>):
#   ac-check.json                .ticket_id (-> "unknown"), .title (-> "")
#   context-manifest.json        .framework object (-> {})
#   complexity-assessment.json   .size (-> "M")
#   execution-results.json       .total/.passing/.failing/.fixes_applied
#                                (numeric, -> 0), .test_files array (-> [])
#
# Output: writes <output_dir>/meta.json, then prints a confirmation to stdout.
#
# Requires: jq. Exit 0 on success, 1 on a usage error; nonzero only if jq is
# missing or the final meta.json write fails.

set -o errexit
set -o nounset
set -o pipefail

if (( $# < 1 )); then
    printf 'Usage: %s <output_dir>\n' "$(basename "$0")" >&2
    exit 1
fi

# Normalize once: base has no trailing slash for filesystem paths; the meta.json
# output_dir field records the directory *with* a trailing slash.
base_dir=${1%/}
meta_path="$base_dir/meta.json"
dir_with_slash="$base_dir/"

# A managed SQLite run owns lifecycle state. This compatibility assembler cannot
# commit a coordinator-fenced snapshot, so refuse to create a second authority.
# Managed callers use runtime lifecycle operations and legacy.export instead.
probe_dir=$(cd "$base_dir" 2>/dev/null && pwd) || {
    printf 'qa-assemble-meta: output directory is not accessible: %s\n' "$base_dir" >&2
    exit 2
}
while [[ "$probe_dir" != "/" ]]; do
    if [[ -f "$probe_dir/.agentic/state/runtime.sqlite3" ]]; then
        printf 'qa-assemble-meta: managed SQLite run detected; use runtime operations and legacy.export\n' >&2
        exit 2
    fi
    probe_dir=$(dirname "$probe_dir")
done

# Pull a string field, defaulting when the file or key is absent/unreadable.
pick_text() {
    local file=$1 query=$2 fallback=$3
    if [[ -r "$file" ]]; then
        jq -r --arg d "$fallback" "$query // \$d" "$file" 2>/dev/null \
            || printf '%s' "$fallback"
    else
        printf '%s' "$fallback"
    fi
}

# Pull a numeric field, coercing strings to numbers, defaulting on any failure.
pick_number() {
    local file=$1 query=$2 fallback=$3
    if [[ -r "$file" ]]; then
        jq -r --argjson d "$fallback" \
            "(($query) // \$d) | (tonumber? // \$d)" "$file" 2>/dev/null \
            || printf '%s' "$fallback"
    else
        printf '%s' "$fallback"
    fi
}

# Pull a nested JSON value (object/array) verbatim, defaulting on any failure.
pick_json() {
    local file=$1 query=$2 fallback=$3
    if [[ -r "$file" ]]; then
        jq -c --argjson d "$fallback" "$query // \$d" "$file" 2>/dev/null \
            || printf '%s' "$fallback"
    else
        printf '%s' "$fallback"
    fi
}

ac_file="$base_dir/ac-check.json"
ctx_file="$base_dir/context-manifest.json"
size_file="$base_dir/complexity-assessment.json"
exec_file="$base_dir/execution-results.json"

ticket_id=$(pick_text "$ac_file" '.ticket_id' 'unknown')
ticket_title=$(pick_text "$ac_file" '.title' '')
framework_json=$(pick_json "$ctx_file" '.framework' '{}')
size_label=$(pick_text "$size_file" '.size' 'M')

total_tests=$(pick_number "$exec_file" '.total' '0')
passing_tests=$(pick_number "$exec_file" '.passing' '0')
failing_tests=$(pick_number "$exec_file" '.failing' '0')
fixes_applied=$(pick_number "$exec_file" '.fixes_applied' '0')
test_files_json=$(pick_json "$exec_file" '.test_files' '[]')

generated_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# Final assembly; this jq call is the only step allowed to fail the run.
jq -n \
    --arg ticket_id "$ticket_id" \
    --arg ticket_title "$ticket_title" \
    --arg generated_at "$generated_at" \
    --arg output_dir "$dir_with_slash" \
    --argjson framework "$framework_json" \
    --argjson test_files "$test_files_json" \
    --argjson total "$total_tests" \
    --argjson passing "$passing_tests" \
    --argjson failing "$failing_tests" \
    --argjson fixes "$fixes_applied" \
    --arg size "$size_label" \
    '{
        skill: "qa-e2e-generator",
        version: "0.1.0",
        ticket_id: $ticket_id,
        ticket_title: $ticket_title,
        generated_at: $generated_at,
        output_dir: $output_dir,
        framework: $framework,
        test_files: $test_files,
        execution_results: {
            total_tests: $total,
            passing: $passing,
            failing: $failing,
            fixes_applied: $fixes
        },
        size_tshirt: $size,
        status: "complete"
    }' > "$meta_path"

printf 'meta.json written to %s\n' "$meta_path"
