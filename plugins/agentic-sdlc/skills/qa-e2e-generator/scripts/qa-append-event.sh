#!/usr/bin/env bash
#
# qa-append-event.sh — record one progress event for a QA generation run.
#
# Appends a single compact JSON object to <output_dir>/events.jsonl. The log is
# an append-only JSONL stream: one self-contained object per line. Each line
# carries a numeric phase, a step name, a UTC timestamp, a status, and any
# caller-supplied extra fields merged on top.
#
# Usage: qa-append-event.sh <output_dir> <phase> <name> <status> [extra_json]
#   output_dir  directory that holds the run's events.jsonl (created if absent)
#   phase       numeric phase, emitted as a raw JSON number (not a string)
#   name        step label (string)
#   status      step status (string)
#   extra_json  optional JSON object; its keys are merged in and win on clash;
#               defaults to {} when omitted or empty
#
# Requires: jq. Exit 0 on success, 1 on a usage error; jq's nonzero status
# aborts the run (strict mode) when phase or extra_json are not valid JSON.

set -o errexit
set -o nounset
set -o pipefail

if (( $# < 4 )); then
    printf 'Usage: %s <output_dir> <phase> <name> <status> [extra_json]\n' \
        "$(basename "$0")" >&2
    exit 1
fi

run_dir=$1
phase_number=$2
step_name=$3
step_status=$4
extra_object=${5:-}

# An absent or blank extra argument collapses to an empty object.
if [[ -z "$extra_object" ]]; then
    extra_object='{}'
fi

mkdir -p "$run_dir"

# A managed SQLite run owns lifecycle state. With coordinator context this
# helper records a fenced runtime event; without it, fail closed instead of
# creating a second authority. Unmanaged legacy fixtures remain supported.
probe_dir=$(cd "$run_dir" 2>/dev/null && pwd) || {
    printf 'qa-append-event: output directory is not accessible: %s\n' "$run_dir" >&2
    exit 2
}
managed_root=''
while [[ "$probe_dir" != "/" ]]; do
    if [[ -f "$probe_dir/.agentic/state/runtime.sqlite3" ]]; then
        managed_root=$probe_dir
        break
    fi
    probe_dir=$(dirname "$probe_dir")
done

if [[ -n "$managed_root" ]]; then
    : "${AGENTIC_RUNTIME_RUN_ID:=}"
    : "${AGENTIC_COORDINATOR_ID:=}"
    : "${AGENTIC_LEASE_EPOCH:=}"
    : "${AGENTIC_EXPECTED_REVISION:=}"
    if [[ -z "$AGENTIC_RUNTIME_RUN_ID" || -z "$AGENTIC_COORDINATOR_ID" ||
          ! "$AGENTIC_LEASE_EPOCH" =~ ^[0-9]+$ ||
          ! "$AGENTIC_EXPECTED_REVISION" =~ ^[0-9]+$ ]]; then
        printf 'qa-append-event: managed SQLite run requires AGENTIC_RUNTIME_RUN_ID, AGENTIC_COORDINATOR_ID, AGENTIC_LEASE_EPOCH, and AGENTIC_EXPECTED_REVISION\n' >&2
        exit 2
    fi
    event_id=$(printf '%s' "$AGENTIC_RUNTIME_RUN_ID:$phase_number:$step_name:$step_status" | shasum -a 256 | cut -c1-32)
    event_payload=$(jq -cn --arg phase "$phase_number" --arg name "$step_name" \
        --arg status "$step_status" --argjson extra "$extra_object" \
        '{phase: $phase, name: $name, status: $status, extra: $extra}')
    request=$(jq -cn --arg run_id "$AGENTIC_RUNTIME_RUN_ID" --arg event_id "$event_id" \
        --arg coordinator_id "$AGENTIC_COORDINATOR_ID" --argjson lease_epoch "$AGENTIC_LEASE_EPOCH" \
        --argjson expected_revision "$AGENTIC_EXPECTED_REVISION" --argjson payload "$event_payload" \
        '{api_version:"1.0.0",operation:"event.record",run_id:$run_id,event_id:$event_id,event_type:"qa.phase",payload:$payload,coordinator_id:$coordinator_id,lease_epoch:$lease_epoch,expected_revision:$expected_revision}')
    request=$(jq --arg root "$managed_root" '.root = $root' <<<"$request")
    runner="$(cd "$(dirname "$0")/../../.." && pwd)/runtime/run.py"
    response=$(python3 "$runner" <<<"$request")
    if ! jq -e '.ok == true' >/dev/null <<<"$response"; then
        printf 'qa-append-event: runtime event.record failed: %s\n' "$response" >&2
        exit 2
    fi
    exit 0
fi

# Base fields first, then a shallow merge (+) of the extra object so callers can
# override any base key. `now | todate` yields an ISO-8601 UTC instant.
event_line=$(
    jq -cn \
        --argjson phase "$phase_number" \
        --arg name "$step_name" \
        --arg status "$step_status" \
        --argjson extra "$extra_object" \
        '{phase: $phase, name: $name, timestamp: (now | todate), status: $status} + $extra'
)

printf '%s\n' "$event_line" >> "$run_dir/events.jsonl"
