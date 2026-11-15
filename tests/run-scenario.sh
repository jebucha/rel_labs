#!/usr/bin/env bash
#
# Executable scenarios for the ascender-inventory-bootstrap capability.
#
# Each scenario is addressable by the id used in the spec's Test Requirement
# blocks:
#
#   tests/run-scenario.sh T-ASCENDER-INVENTORY-BOOTSTRAP-001
#   tests/run-scenario.sh all
#
# -001..-004, -006 and -007 drive the real playbook against a live Ascender
# (controller_cli.cfg in the repo root or CONTROLLER_* environment variables),
# arranging the state each scenario's GIVEN clause needs first.
#
# -005 runs against tests/stub_ascender.py: the double accepts the creates but
# never returns the inventory source, so the retry budget is exercised without
# a live instance (the scenario takes ~60-70s).
#
# Exit codes: 0 pass, 1 assertion failure, 2 playbook failure, 3 prerequisite
# unmet (nothing was verified).
set -uo pipefail

REPO_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd) || exit 3
cd "$REPO_ROOT" || exit 3

PLAYBOOK=ascender_as_code.yml
STATE_PLAYBOOK=tests/scenario_state.yml
STUB=tests/stub_ascender.py
PLAY_TIMEOUT=${PLAY_TIMEOUT:-120}
EXHAUST_TIMEOUT=${EXHAUST_TIMEOUT:-180}

LOG=
STUB_LOG=
STUB_PID=

cleanup() {
    [ -n "$STUB_PID" ] && kill "$STUB_PID" 2>/dev/null
    [ -n "$LOG" ] && rm -f "$LOG"
    [ -n "$STUB_LOG" ] && rm -f "$STUB_LOG"
}
trap cleanup EXIT

SCENARIOS=(
    T-ASCENDER-INVENTORY-BOOTSTRAP-001
    T-ASCENDER-INVENTORY-BOOTSTRAP-002
    T-ASCENDER-INVENTORY-BOOTSTRAP-003
    T-ASCENDER-INVENTORY-BOOTSTRAP-004
    T-ASCENDER-INVENTORY-BOOTSTRAP-005
    T-ASCENDER-INVENTORY-BOOTSTRAP-006
    T-ASCENDER-INVENTORY-BOOTSTRAP-007
)

usage() {
    printf 'usage: %s <%s|all>\n' "$0" "$(IFS='|'; printf '%s' "${SCENARIOS[*]}")" >&2
}

pass() {
    printf 'PASS: %s\n' "$1"
}

fail_assert() {
    printf 'FAIL: %s\n' "$*" >&2
    if [ -n "$LOG" ] && [ -f "$LOG" ]; then
        printf -- '--- last 20 lines of the run log ---\n' >&2
        tail -20 "$LOG" >&2
    fi
    exit 1
}

fail_prereq() {
    printf 'PREREQUISITE UNMET: %s\n' "$*" >&2
    exit 3
}

require_live_ascender() {
    if [ ! -f controller_cli.cfg ] && [ -z "${CONTROLLER_HOST:-}" ]; then
        fail_prereq "no controller_cli.cfg in $REPO_ROOT and CONTROLLER_HOST is unset; this scenario needs a live Ascender"
    fi
    command -v ansible-playbook >/dev/null 2>&1 || fail_prereq "ansible-playbook is not on PATH"
}

run_playbook() {
    local timeout=$1
    shift
    LOG=$(mktemp)
    if timeout "$timeout" ansible-playbook "$PLAYBOOK" "$@" >"$LOG" 2>&1; then
        RC=0
    else
        RC=$?
    fi
}

arrange_state() {
    local scenario=$1
    printf 'setting up Ascender state for %s\n' "$scenario"
    if ! timeout "$PLAY_TIMEOUT" ansible-playbook "$STATE_PLAYBOOK" -e "scenario=$scenario"; then
        fail_assert "state setup for $scenario failed"
    fi
}

# Prints the first result line of a task ("ok:", "changed:", "fatal:", ...).
task_result() {
    awk -v name="$1" '
        index($0, "TASK [" name "]") { found = 1; next }
        found && /^TASK \[/ { exit }
        found && /^(ok|changed|fatal|skipping|failed):/ { print; exit }
    ' "$LOG"
}

task_line() {
    grep -n -F "TASK [$1]" "$LOG" | head -1 | cut -d: -f1
}

assert_rc() {
    local expected=$1
    [ "$RC" -eq "$expected" ] || fail_assert "expected exit code $expected, got $RC"
}

assert_task_ok() {
    local result
    result=$(task_result "$1")
    case "$result" in
        ok:*|changed:*) ;;
        *) fail_assert "task '$1' did not succeed (result: ${result:-missing})" ;;
    esac
}

assert_task_unchanged() {
    local result
    result=$(task_result "$1")
    case "$result" in
        ok:*) ;;
        changed:*) fail_assert "task '$1' reported changed, expected no change" ;;
        *) fail_assert "task '$1' did not report ok (result: ${result:-missing})" ;;
    esac
}

assert_task_absent() {
    if grep -q -F "TASK [$1]" "$LOG"; then
        fail_assert "task '$1' ran but should not have"
    fi
}

assert_order() {
    local first second first_line second_line
    first_line=$(task_line "$1")
    second_line=$(task_line "$2")
    [ -n "$first_line" ] || fail_assert "task '$1' did not run"
    [ -n "$second_line" ] || fail_assert "task '$2' did not run"
    [ "$first_line" -lt "$second_line" ] || fail_assert "task '$1' did not run before '$2'"
}

assert_recap_clean() {
    local recap
    recap=$(grep -E '^localhost +:' "$LOG" | tail -1)
    [ -n "$recap" ] || fail_assert "no play recap in the run log"
    case "$recap" in
        *failed=0*) ;;
        *) fail_assert "play recap reports failures: $recap" ;;
    esac
    case "$recap" in
        *skipped=0*) ;;
        *) fail_assert "play recap reports skipped tasks: $recap" ;;
    esac
}

assert_no_retries() {
    if grep -q 'FAILED - RETRYING' "$LOG"; then
        fail_assert "the run retried a visibility wait; a steady-state run must pass on the first poll"
    fi
}

assert_message() {
    grep -q -F "$1" "$LOG" || fail_assert "expected message not found in the run log: $1"
}

wait_for_port() {
    local port=$1 i
    for i in $(seq 1 100); do
        if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
            return 0
        fi
        sleep 0.1
    done
    return 1
}

# --- scenarios ------------------------------------------------------------

scenario_001() {
    require_live_ascender
    arrange_state "$1"
    run_playbook "$PLAY_TIMEOUT"
    assert_rc 0
    assert_recap_clean
    assert_task_ok "Create default inventory"
    assert_task_ok "Poll for 20031 Inventory visibility"
    assert_task_ok "Add 20031 inventory source"
    assert_task_ok "Poll for 20031-source visibility"
    assert_task_ok "Update 2003 inventory"
    assert_order "Poll for 20031 Inventory visibility" "Add 20031 inventory source"
    assert_order "Poll for 20031-source visibility" "Update 2003 inventory"
    pass "$1"
}

scenario_002() {
    require_live_ascender
    arrange_state "$1"
    run_playbook "$PLAY_TIMEOUT"
    assert_rc 0
    assert_recap_clean
    assert_task_ok "Add 20031 inventory source"
    assert_task_ok "Poll for 20031-source visibility"
    assert_task_ok "Update 2003 inventory"
    pass "$1"
}

scenario_003() {
    require_live_ascender
    arrange_state "$1"
    run_playbook "$PLAY_TIMEOUT"
    assert_rc 0
    assert_task_ok "Poll for 20031 Inventory visibility"
    assert_order "Poll for 20031 Inventory visibility" "Add 20031 inventory source"
    pass "$1"
}

scenario_004() {
    require_live_ascender
    arrange_state "$1"
    run_playbook "$PLAY_TIMEOUT"
    assert_rc 0
    assert_task_ok "Poll for 20031-source visibility"
    assert_order "Poll for 20031-source visibility" "Update 2003 inventory"
    pass "$1"
}

scenario_005() {
    command -v python3 >/dev/null 2>&1 || fail_prereq "python3 is required for the stub Ascender"
    local port
    port=$(python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()') \
        || fail_prereq "could not allocate a local port for the stub"

    STUB_LOG=$(mktemp)
    python3 "$STUB" --port "$port" 2>"$STUB_LOG" &
    STUB_PID=$!
    wait_for_port "$port" || fail_prereq "the stub Ascender did not start on port $port: $(cat "$STUB_LOG")"

    CONTROLLER_HOST="http://127.0.0.1:$port" \
    CONTROLLER_USERNAME=stub \
    CONTROLLER_PASSWORD=stub \
    CONTROLLER_VERIFY_SSL=false \
        run_playbook "$EXHAUST_TIMEOUT"

    assert_rc 2
    assert_task_ok "Poll for 20031 Inventory visibility"
    if ! grep -q 'FAILED - RETRYING.*Poll for 20031-source visibility' "$LOG"; then
        fail_assert "the source visibility wait never retried"
    fi
    assert_message "20031-source was not visible in inventory 20031 Inventory after 30 attempts"
    assert_task_absent "Update 2003 inventory"
    pass "$1"
}

scenario_006() {
    require_live_ascender
    arrange_state "$1"
    run_playbook "$PLAY_TIMEOUT"
    assert_rc 0
    assert_task_ok "Update 2003 inventory"
    if grep -qiE 'not.?found' "$LOG"; then
        fail_assert "the update task reported a not-found error"
    fi
    pass "$1"
}

scenario_007() {
    require_live_ascender
    arrange_state "$1"
    run_playbook "$PLAY_TIMEOUT"
    assert_rc 0
    assert_no_retries
    assert_task_unchanged "Create default inventory"
    assert_task_unchanged "Add 20031 inventory source"
    assert_task_ok "Update 2003 inventory"
    pass "$1"
}

# --- dispatch -------------------------------------------------------------

main() {
    local scenario=${1:-}
    if [ -z "$scenario" ]; then
        usage
        exit 3
    fi

    if [ "$scenario" = all ]; then
        local id failed=0
        for id in "${SCENARIOS[@]}"; do
            "$0" "$id" || failed=1
        done
        exit "$failed"
    fi

    case "$scenario" in
        T-ASCENDER-INVENTORY-BOOTSTRAP-001) scenario_001 "$scenario" ;;
        T-ASCENDER-INVENTORY-BOOTSTRAP-002) scenario_002 "$scenario" ;;
        T-ASCENDER-INVENTORY-BOOTSTRAP-003) scenario_003 "$scenario" ;;
        T-ASCENDER-INVENTORY-BOOTSTRAP-004) scenario_004 "$scenario" ;;
        T-ASCENDER-INVENTORY-BOOTSTRAP-005) scenario_005 "$scenario" ;;
        T-ASCENDER-INVENTORY-BOOTSTRAP-006) scenario_006 "$scenario" ;;
        T-ASCENDER-INVENTORY-BOOTSTRAP-007) scenario_007 "$scenario" ;;
        *)
            printf 'unknown scenario: %s\n' "$scenario" >&2
            usage
            exit 3
            ;;
    esac
}

main "$@"
