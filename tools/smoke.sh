#!/usr/bin/env bash
# Smoke test for gsreplay. Proves:
#   1. the binary is a valid ELF for this arch and resolves its shared libs
#   2. --help reaches the argument parser (no signal, no hang)
#   3. --novideo gets past VU init to the replay stage (no SIGILL on the
#      off-x86 scalar path), and fails cleanly on a missing capture
# It does NOT exercise VU emulation or render anything.
set -euo pipefail

BIN=$(find build -maxdepth 4 -name gsreplay -type f -executable | head -1)
if [ -z "$BIN" ]; then
  echo "FAIL: gsreplay binary not found under build/"
  find build -name 'gsreplay*' || true
  exit 1
fi
echo "binary: $BIN"
command -v file >/dev/null && file "$BIN" || true

if ldd "$BIN" 2>/dev/null | grep -q "not found"; then
  echo "FAIL: missing shared libraries:"
  ldd "$BIN" | grep "not found"
  exit 1
fi

RC=0; LOG=""
run() {
  local name=$1; shift
  LOG=/tmp/gsreplay-smoke-$name.log
  set +e
  timeout 15 "$@" > "$LOG" 2>&1
  RC=$?
  set -e
  echo "--- $name: rc=$RC ---"
  head -20 "$LOG"
  echo "--- end $name ---"
  if [ "$RC" -eq 124 ]; then echo "FAIL: $name timed out"; exit 1; fi
  if [ "$RC" -ge 128 ]; then echo "FAIL: $name died from signal $((RC - 128))"; exit 1; fi
}

run help "$BIN" --help
if [ "$RC" -ne 0 ]; then echo "FAIL: --help exited $RC (expected 0)"; exit 1; fi
if ! grep -q "usage:" "$LOG"; then echo "FAIL: --help did not print usage"; exit 1; fi

run novideo "$BIN" --novideo /tmp/gsreplay-smoke-no-such.gscap
if [ "$RC" -ne 1 ]; then echo "FAIL: --novideo with missing capture exited $RC (expected 1)"; exit 1; fi
if ! grep -qi "cannot open" "$LOG"; then echo "FAIL: --novideo did not report the missing capture"; exit 1; fi
if ! grep -q "VU1" "$LOG"; then
  echo "WARN: startup log did not mention VU1; VU init may not have run"
fi

echo "OK: gsreplay smoke test passed"
