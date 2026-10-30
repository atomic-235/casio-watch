#!/usr/bin/env bash
# Keyboard-only end-to-end scenarios against the mock watch, driven through tmux.
set -uo pipefail

SESSION="casio-e2e"
DIR="$(cd "$(dirname "$0")/.." && pwd)"
PASS=0
FAIL=0

cleanup() {
  tmux kill-session -t "$SESSION" 2>/dev/null || true
}
trap cleanup EXIT

start() {
  tmux kill-session -t "$SESSION" 2>/dev/null || true
  tmux new-session -d -s "$SESSION" -x 120 -y 40 \
    "cd '$DIR' && direnv exec . casio-watch-tui --mock"
}

send() { tmux send-keys -t "$SESSION" "$@"; }
type_text() { tmux send-keys -t "$SESSION" -l "$1"; }
capture() { tmux capture-pane -p -t "$SESSION"; }

wait_for() {
  local pattern="$1" tries="${2:-60}"
  for _ in $(seq "$tries"); do
    if capture | grep -q "$pattern"; then return 0; fi
    sleep 0.25
  done
  return 1
}

check() {
  local name="$1" pattern="$2"
  if capture | grep -q "$pattern"; then
    echo "PASS  $name"; PASS=$((PASS + 1))
  else
    echo "FAIL  $name (missing: $pattern)"
    echo "----- screen -----"; capture; echo "------------------"
    FAIL=$((FAIL + 1))
  fi
}

check_absent() {
  local name="$1" pattern="$2"
  if capture | grep -q "$pattern"; then
    echo "FAIL  $name (unexpected: $pattern)"
    echo "----- screen -----"; capture; echo "------------------"
    FAIL=$((FAIL + 1))
  else
    echo "PASS  $name"; PASS=$((PASS + 1))
  fi
}

start
if ! wait_for "no watch"; then
  echo "FAIL  TUI did not start"; capture; exit 1
fi
echo "PASS  TUI starts"; PASS=$((PASS + 1))
check "starts in settings panel" "Settings"
check "starts in normal mode" "NORMAL"

send s
if wait_for "battery: 80%"; then
  echo "PASS  mock connect shows battery"; PASS=$((PASS + 1))
else
  echo "FAIL  mock connect failed"; capture; FAIL=$((FAIL + 1))
fi
check "state ready" "ready"

send 2
sleep 0.4
check "panel 2 is alarms" "Alarms"

send Enter
sleep 0.4
check "enter opens edit prompt" "EDIT"
type_text "0730"
sleep 0.3
send Enter
sleep 0.4
check "alarm time committed" "07:30"
check "back to normal mode" "NORMAL"

send w
sleep 0.4
check "write asks for confirmation" "Write these changes"
send Enter
if wait_for "Changes written and verified"; then
  echo "PASS  write confirms read-back"; PASS=$((PASS + 1))
else
  echo "FAIL  write confirmation missing"; capture; FAIL=$((FAIL + 1))
fi

send 1
sleep 0.4
check "panel 1 is settings" "Time format"

send /
sleep 0.3
check "filter prompt opens" "EDIT"
type_text "light"
send Enter
sleep 0.4
check "filter narrows rows" "Light duration"
check_absent "filter hides other rows" "Time format"

send /
sleep 0.3
send Enter
sleep 0.4
check "same filter clears" "Time format"

send "?"
sleep 0.4
check "help opens" "Keys (normal mode)"
send Escape
sleep 0.3
check "help closes" "Settings"

echo
echo "passed: $PASS  failed: $FAIL"
[ "$FAIL" -eq 0 ]
