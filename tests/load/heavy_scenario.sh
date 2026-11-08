#!/usr/bin/env bash
set -u

# Heavy load scenario for Praktikant service.
# Goals:
# 1) Simulate many user registrations and auth flows in parallel.
# 2) Measure stability under load (HTTP statuses, success/fail ratio).
# 3) Exercise both public and authenticated endpoints.
#
# Usage examples:
#   bash tests/load/heavy_scenario.sh
#   BASE_URL="http://localhost:8000" TOTAL_USERS=120 CONCURRENCY=24 ROUNDS=8 bash tests/load/heavy_scenario.sh
#
# Notes:
# - The script is intentionally aggressive and can trigger rate limits (429) by design.
# - Registration requires unique email+phone; the script auto-generates both.
# - Email confirmation uses test bypass code 335335.

BASE_URL="${BASE_URL:-http://localhost:8000}"
TOTAL_USERS="${TOTAL_USERS:-60}"
CONCURRENCY="${CONCURRENCY:-12}"
ROUNDS="${ROUNDS:-6}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-20}"
ORIGIN_HEADER="${ORIGIN_HEADER:-$BASE_URL}"

SCRIPT_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
RUN_ID="${RUN_ID:-$(date +%s)}"
STATE_DIR="${STATE_DIR:-/tmp/praktikant-load-${RUN_ID}}"
RESULTS_FILE="${STATE_DIR}/results.tsv"

mkdir -p "$STATE_DIR"

json_field() {
  local key="$1"
  node -e '
let buf="";
process.stdin.on("data",c=>buf+=c).on("end",()=>{
  try {
    const o = JSON.parse(buf || "{}");
    const v = o[process.argv[1]];
    if (v === undefined || v === null) process.stdout.write("");
    else process.stdout.write(String(v));
  } catch {
    process.stdout.write("");
  }
});' "$key"
}

http_json() {
  local method="$1"
  local url="$2"
  local body="${3:-}"
  local cookie_file="${4:-}"
  local response_file
  response_file="$(mktemp)"
  local code

  if [[ -n "$body" ]]; then
    if [[ -n "$cookie_file" ]]; then
      code="$(curl -sS -m "$TIMEOUT_SECONDS" -o "$response_file" -w "%{http_code}" \
        -X "$method" "$url" \
        -H "Content-Type: application/json" \
        -H "Origin: ${ORIGIN_HEADER}" \
        -H "X-Device-Fingerprint: load_fp_${RUN_ID}" \
        -b "$cookie_file" -c "$cookie_file" \
        --data "$body")"
    else
      code="$(curl -sS -m "$TIMEOUT_SECONDS" -o "$response_file" -w "%{http_code}" \
        -X "$method" "$url" \
        -H "Content-Type: application/json" \
        -H "Origin: ${ORIGIN_HEADER}" \
        -H "X-Device-Fingerprint: load_fp_${RUN_ID}" \
        --data "$body")"
    fi
  else
    if [[ -n "$cookie_file" ]]; then
      code="$(curl -sS -m "$TIMEOUT_SECONDS" -o "$response_file" -w "%{http_code}" \
        -X "$method" "$url" \
        -H "Origin: ${ORIGIN_HEADER}" \
        -H "X-Device-Fingerprint: load_fp_${RUN_ID}" \
        -b "$cookie_file" -c "$cookie_file")"
    else
      code="$(curl -sS -m "$TIMEOUT_SECONDS" -o "$response_file" -w "%{http_code}" \
        -X "$method" "$url" \
        -H "Origin: ${ORIGIN_HEADER}" \
        -H "X-Device-Fingerprint: load_fp_${RUN_ID}")"
    fi
  fi

  local body_out
  body_out="$(<"$response_file")"
  rm -f "$response_file"
  printf "%s\n%s\n" "$code" "$body_out"
}

append_result() {
  local user_id="$1"
  local stage="$2"
  local code="$3"
  local note="${4:-}"
  printf "%s\t%s\t%s\t%s\n" "$user_id" "$stage" "$code" "$note" >> "$RESULTS_FILE"
}

worker() {
  local user_id="$1"
  local email="load_${RUN_ID}_${user_id}@example.com"
  local phone
  phone="$(printf "79%09d" "$((RUN_ID % 1000000000 + user_id))")"
  local pass="Pass_${RUN_ID}_${user_id}"
  local cookie_file="${STATE_DIR}/cookie_${user_id}.txt"
  : > "$cookie_file"

  local out code body step_required step_token

  # 1) register
  out="$(http_json "POST" "${BASE_URL}/api/register" "{\"name\":\"LoadUser${user_id}\",\"email\":\"${email}\",\"phone\":\"${phone}\",\"password\":\"${pass}\",\"termsAccepted\":true}")"
  code="$(printf "%s\n" "$out" | sed -n '1p')"
  body="$(printf "%s\n" "$out" | sed -n '2,$p')"
  append_result "$user_id" "register" "$code"
  if [[ "$code" != "201" && "$code" != "409" ]]; then
    return 0
  fi

  # 2) confirm email with test code
  out="$(http_json "POST" "${BASE_URL}/api/email/verify/confirm" "{\"email\":\"${email}\",\"code\":\"335335\"}" "$cookie_file")"
  code="$(printf "%s\n" "$out" | sed -n '1p')"
  body="$(printf "%s\n" "$out" | sed -n '2,$p')"
  append_result "$user_id" "email_confirm" "$code"

  # 3) login
  out="$(http_json "POST" "${BASE_URL}/api/login" "{\"identifier\":\"${email}\",\"password\":\"${pass}\"}" "$cookie_file")"
  code="$(printf "%s\n" "$out" | sed -n '1p')"
  body="$(printf "%s\n" "$out" | sed -n '2,$p')"
  append_result "$user_id" "login" "$code"

  if [[ "$code" == "202" ]]; then
    step_required="$(printf "%s" "$body" | json_field "stepUpRequired")"
    step_token="$(printf "%s" "$body" | json_field "stepUpToken")"
    if [[ "$step_required" == "true" && -n "$step_token" ]]; then
      out="$(http_json "POST" "${BASE_URL}/api/login/step-up/verify" "{\"stepUpToken\":\"${step_token}\",\"emailCode\":\"335335\"}" "$cookie_file")"
      code="$(printf "%s\n" "$out" | sed -n '1p')"
      append_result "$user_id" "stepup_verify" "$code"
      if [[ "$code" != "200" ]]; then
        return 0
      fi
    fi
  elif [[ "$code" != "200" ]]; then
    return 0
  fi

  # 4) authenticated rounds
  local i
  for i in $(seq 1 "$ROUNDS"); do
    out="$(http_json "GET" "${BASE_URL}/api/me" "" "$cookie_file")"
    code="$(printf "%s\n" "$out" | sed -n '1p')"
    append_result "$user_id" "me" "$code"

    out="$(http_json "GET" "${BASE_URL}/api/my/subscription" "" "$cookie_file")"
    code="$(printf "%s\n" "$out" | sed -n '1p')"
    append_result "$user_id" "my_subscription" "$code"
  done
}

print_summary() {
  echo
  echo "=== LOAD TEST SUMMARY ==="
  echo "BASE_URL=${BASE_URL}"
  echo "TOTAL_USERS=${TOTAL_USERS}"
  echo "CONCURRENCY=${CONCURRENCY}"
  echo "ROUNDS=${ROUNDS}"
  echo "RESULTS_FILE=${RESULTS_FILE}"
  echo
  awk -F '\t' '
  {
    stage=$2;
    code=$3;
    key=stage "|" code;
    total[stage]++;
    by[key]++;
  }
  END {
    print "Per stage status distribution:";
    for (k in by) {
      split(k,a,"|");
      printf "  %-18s HTTP %-3s : %d\n", a[1], a[2], by[k];
    }
    print "";
    print "Stage totals:";
    for (s in total) {
      printf "  %-18s total=%d\n", s, total[s];
    }
  }' "$RESULTS_FILE"
  echo
  echo "Interpretation:"
  echo "- 2xx dominates -> service handles scenario reasonably."
  echo "- 429 on auth/email endpoints under high pressure is expected due rate limiting."
  echo "- many 5xx -> investigate server logs and DB/mail bottlenecks."
}

echo "Starting heavy scenario..."
echo "State dir: ${STATE_DIR}"
: > "$RESULTS_FILE"
running_jobs=0
for i in $(seq 1 "$TOTAL_USERS"); do
  worker "$i" &
  running_jobs=$((running_jobs + 1))
  if [[ "$running_jobs" -ge "$CONCURRENCY" ]]; then
    wait -n
    running_jobs=$((running_jobs - 1))
  fi
done
wait

print_summary
