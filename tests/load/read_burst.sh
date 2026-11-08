#!/usr/bin/env bash
set -u

# Fast read-only burst test for static and public endpoints.
#
# Usage:
#   bash tests/load/read_burst.sh
#   BASE_URL=http://localhost:8000 REQUESTS=4000 CONCURRENCY=80 bash tests/load/read_burst.sh

BASE_URL="${BASE_URL:-http://localhost:8000}"
REQUESTS="${REQUESTS:-2000}"
CONCURRENCY="${CONCURRENCY:-50}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-10}"

TARGETS=(
  "/"
  "/index.html"
  "/login.html"
  "/register.html"
  "/verify-email.html"
  "/reset-password.html"
  "/privacy-policy.html"
  "/auth.js"
)

STATUS_FILE="$(mktemp)"

request_one() {
  local idx="$1"
  local targets_len="${#TARGETS[@]}"
  if [[ "$targets_len" -eq 0 ]]; then
    echo "000" >> "$STATUS_FILE"
    return
  fi
  local target="${TARGETS[$((idx % targets_len))]}"
  curl -sS -m "$TIMEOUT_SECONDS" -o /dev/null -w "%{http_code}\n" "${BASE_URL}${target}" >> "$STATUS_FILE" || echo "000" >> "$STATUS_FILE"
}

running_jobs=0
for i in $(seq 1 "$REQUESTS"); do
  request_one "$i" &
  running_jobs=$((running_jobs + 1))
  if [[ "$running_jobs" -ge "$CONCURRENCY" ]]; then
    wait -n
    running_jobs=$((running_jobs - 1))
  fi
done
wait

echo "=== READ BURST SUMMARY ==="
echo "BASE_URL=${BASE_URL}"
echo "REQUESTS=${REQUESTS}"
echo "CONCURRENCY=${CONCURRENCY}"
echo
awk '{ cnt[$1]++ } END { for (k in cnt) printf "HTTP %s: %d\n", k, cnt[k] }' "$STATUS_FILE" | sort

rm -f "$STATUS_FILE"
