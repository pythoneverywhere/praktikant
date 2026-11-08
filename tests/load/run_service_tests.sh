#!/usr/bin/env bash
set -euo pipefail

# API-only suite for current FastAPI backend.
# Functional mode uses real endpoints only (no direct DB writes).
# Load mode delegates to tests/load/heavy_scenario.sh.

BASE_URL="${BASE_URL:-http://localhost:8000}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-20}"
ORIGIN_HEADER="${ORIGIN_HEADER:-$BASE_URL}"
ADMIN_IDENTIFIER="${ADMIN_IDENTIFIER:-}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-}"
TEST_BYPASS_CODE="${TEST_BYPASS_CODE:-335335}"
HEAVY_TOTAL_USERS="${HEAVY_TOTAL_USERS:-80}"
HEAVY_CONCURRENCY="${HEAVY_CONCURRENCY:-16}"
HEAVY_ROUNDS="${HEAVY_ROUNDS:-6}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
RUN_ID="${RUN_ID:-$(date +%s)}"
STATE_DIR="${STATE_DIR:-/tmp/praktikant-suite-${RUN_ID}}"
RESULTS_FILE="${STATE_DIR}/results.tsv"
mkdir -p "${STATE_DIR}"

cd "${PROJECT_ROOT}" || exit 1

log() {
  local level="$1"; shift
  printf "[%s] %s\n" "${level}" "$*"
}

fail() {
  log "ОШИБКА" "$*"
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Команда '$1' не найдена."
}

require_cmd curl
require_cmd node

json_get() {
  local path="$1"
  node -e '
const p = String(process.argv[1] || "");
let buf = "";
process.stdin.on("data", (c) => (buf += c)).on("end", () => {
  try {
    const obj = JSON.parse(buf || "{}");
    if (!p) return process.stdout.write("");
    const value = p.split(".").reduce((acc, key) => (acc == null ? undefined : acc[key]), obj);
    process.stdout.write(value == null ? "" : String(value));
  } catch {
    process.stdout.write("");
  }
});' "${path}"
}

http_json() {
  local method="$1"
  local url="$2"
  local body="${3:-}"
  local cookie_file="${4:-}"
  local cookie_header=""
  if [[ -n "${cookie_file}" && -f "${cookie_file}" ]]; then
    cookie_header="$(awk 'BEGIN{FS="\t"} $0 !~ /^#/ && NF>=7 {print $6"="$7; exit}' "${cookie_file}")"
  fi
  local response_file
  response_file="$(mktemp)"
  local code

  if [[ -n "${body}" ]]; then
    if [[ -n "${cookie_file}" ]]; then
      code="$(curl -sS -m "${TIMEOUT_SECONDS}" -o "${response_file}" -w "%{http_code}" \
        -X "${method}" "${url}" \
        -H "Content-Type: application/json" \
        -H "Origin: ${ORIGIN_HEADER}" \
        -H "X-Device-Fingerprint: test_fp_${RUN_ID}" \
        ${cookie_header:+-H "Cookie: ${cookie_header}"} \
        -b "${cookie_file}" -c "${cookie_file}" \
        --data "${body}" || echo "000")"
    else
      code="$(curl -sS -m "${TIMEOUT_SECONDS}" -o "${response_file}" -w "%{http_code}" \
        -X "${method}" "${url}" \
        -H "Content-Type: application/json" \
        -H "Origin: ${ORIGIN_HEADER}" \
        -H "X-Device-Fingerprint: test_fp_${RUN_ID}" \
        --data "${body}" || echo "000")"
    fi
  else
    if [[ -n "${cookie_file}" ]]; then
      code="$(curl -sS -m "${TIMEOUT_SECONDS}" -o "${response_file}" -w "%{http_code}" \
        -X "${method}" "${url}" \
        -H "Origin: ${ORIGIN_HEADER}" \
        -H "X-Device-Fingerprint: test_fp_${RUN_ID}" \
        ${cookie_header:+-H "Cookie: ${cookie_header}"} \
        -b "${cookie_file}" -c "${cookie_file}" || echo "000")"
    else
      code="$(curl -sS -m "${TIMEOUT_SECONDS}" -o "${response_file}" -w "%{http_code}" \
        -X "${method}" "${url}" \
        -H "Origin: ${ORIGIN_HEADER}" \
        -H "X-Device-Fingerprint: test_fp_${RUN_ID}" || echo "000")"
    fi
  fi
  local body_out
  body_out="$(<"${response_file}")"
  rm -f "${response_file}"
  printf "%s\n%s\n" "${code}" "${body_out}"
}

append_result() {
  local stage="$1"
  local code="$2"
  local note="${3:-}"
  printf "%s\t%s\t%s\n" "${stage}" "${code}" "${note}" >> "${RESULTS_FILE}"
}

expect_code() {
  local stage="$1"
  local got="$2"
  shift 2
  local expected
  for expected in "$@"; do
    [[ "${got}" == "${expected}" ]] && return 0
  done
  fail "Этап '${stage}' вернул HTTP ${got}, ожидалось: $*"
}

check_server() {
  log "ИНФО" "Проверка доступности сервера: ${BASE_URL}"
  local out code
  out="$(http_json "GET" "${BASE_URL}/index.html")"
  code="$(printf "%s\n" "${out}" | sed -n '1p')"
  [[ "${code}" == "200" ]] || fail "Сервер недоступен (HTTP ${code}). Запустите FastAPI backend."
  log "OK" "Сервер отвечает."
}

register_verify_login_user() {
  local name="$1"
  local email="$2"
  local phone="$3"
  local password="$4"
  local cookie_file="$5"
  : > "${cookie_file}"
  local out code

  out="$(http_json "POST" "${BASE_URL}/api/register" "{\"name\":\"${name}\",\"email\":\"${email}\",\"phone\":\"${phone}\",\"password\":\"${password}\",\"termsAccepted\":true}")"
  code="$(printf "%s\n" "${out}" | sed -n '1p')"
  append_result "register:${email}" "${code}"
  expect_code "register:${email}" "${code}" "200" "409"

  out="$(http_json "POST" "${BASE_URL}/api/email/verify/confirm" "{\"email\":\"${email}\",\"code\":\"${TEST_BYPASS_CODE}\"}" "${cookie_file}")"
  code="$(printf "%s\n" "${out}" | sed -n '1p')"
  append_result "email_confirm:${email}" "${code}"
  expect_code "email_confirm:${email}" "${code}" "200" "400"

  out="$(http_json "POST" "${BASE_URL}/api/login" "{\"identifier\":\"${email}\",\"password\":\"${password}\"}" "${cookie_file}")"
  code="$(printf "%s\n" "${out}" | sed -n '1p')"
  local body stepup_required stepup_token
  body="$(printf "%s\n" "${out}" | sed -n '2,$p')"
  append_result "login:${email}" "${code}"
  expect_code "login:${email}" "${code}" "200"
  stepup_required="$(printf "%s" "${body}" | json_get "stepUpRequired")"
  if [[ "${stepup_required}" == "true" ]]; then
    stepup_token="$(printf "%s" "${body}" | json_get "stepUpToken")"
    [[ -n "${stepup_token}" ]] || fail "Не получен step-up токен для ${email}"
    out="$(http_json "POST" "${BASE_URL}/api/login/step-up/verify" "{\"stepUpToken\":\"${stepup_token}\",\"emailCode\":\"${TEST_BYPASS_CODE}\"}" "${cookie_file}")"
    code="$(printf "%s\n" "${out}" | sed -n '1p')"
    append_result "stepup_verify:${email}" "${code}"
    expect_code "stepup_verify:${email}" "${code}" "200"
  fi
}

login_admin() {
  [[ -n "${ADMIN_IDENTIFIER}" ]] || fail "Установите ADMIN_IDENTIFIER (email/phone админа)"
  [[ -n "${ADMIN_PASSWORD}" ]] || fail "Установите ADMIN_PASSWORD (пароль админа)"
  local cookie_file="$1"
  : > "${cookie_file}"
  local out code body stepup_required stepup_token
  out="$(http_json "POST" "${BASE_URL}/api/login" "{\"identifier\":\"${ADMIN_IDENTIFIER}\",\"password\":\"${ADMIN_PASSWORD}\"}" "${cookie_file}")"
  code="$(printf "%s\n" "${out}" | sed -n '1p')"
  body="$(printf "%s\n" "${out}" | sed -n '2,$p')"
  append_result "admin_login" "${code}"
  expect_code "admin_login" "${code}" "200"
  stepup_required="$(printf "%s" "${body}" | json_get "stepUpRequired")"
  if [[ "${stepup_required}" == "true" ]]; then
    stepup_token="$(printf "%s" "${body}" | json_get "stepUpToken")"
    [[ -n "${stepup_token}" ]] || fail "Не получен step-up токен админа"
    out="$(http_json "POST" "${BASE_URL}/api/login/step-up/verify" "{\"stepUpToken\":\"${stepup_token}\",\"emailCode\":\"${TEST_BYPASS_CODE}\"}" "${cookie_file}")"
    code="$(printf "%s\n" "${out}" | sed -n '1p')"
    append_result "admin_stepup_verify" "${code}"
    expect_code "admin_stepup_verify" "${code}" "200"
  fi
}

assert_admin_session() {
  local cookie_file="$1"
  local out code body role
  out="$(http_json "GET" "${BASE_URL}/api/me" "" "${cookie_file}")"
  code="$(printf "%s\n" "${out}" | sed -n '1p')"
  body="$(printf "%s\n" "${out}" | sed -n '2,$p')"
  append_result "admin_me_check" "${code}"
  if [[ "${code}" != "200" ]]; then
    fail "Админ-сессия недействительна (HTTP ${code}). Проверьте ADMIN_IDENTIFIER/ADMIN_PASSWORD и вход."
  fi
  role="$(printf "%s" "${body}" | json_get "user.role")"
  if [[ "${role}" != "admin" ]]; then
    fail "Пользователь под ADMIN_IDENTIFIER не является админом (role='${role}')."
  fi
}

run_functional_suite() {
  : > "${RESULTS_FILE}"
  log "ИНФО" "Запуск API-only функционального прогона"
  local out code body
  local admin_cookie ref_cookie buyer1_cookie buyer2_cookie
  admin_cookie="${STATE_DIR}/cookie_admin.txt"
  ref_cookie="${STATE_DIR}/cookie_ref.txt"
  buyer1_cookie="${STATE_DIR}/cookie_buyer1.txt"
  buyer2_cookie="${STATE_DIR}/cookie_buyer2.txt"

  local ref_email buyer1_email buyer2_email
  local ref_phone buyer1_phone buyer2_phone
  local ref_password buyer1_password buyer2_password
  ref_email="load_ref_${RUN_ID}@example.com"
  buyer1_email="load_b1_${RUN_ID}@example.com"
  buyer2_email="load_b2_${RUN_ID}@example.com"
  ref_phone="$(printf "79%09d" "$((RUN_ID % 1000000000 + 101))")"
  buyer1_phone="$(printf "79%09d" "$((RUN_ID % 1000000000 + 102))")"
  buyer2_phone="$(printf "79%09d" "$((RUN_ID % 1000000000 + 103))")"
  ref_password="Pass_${RUN_ID}_ref"
  buyer1_password="Pass_${RUN_ID}_b1"
  buyer2_password="Pass_${RUN_ID}_b2"

  for p in "/" "/index.html" "/login.html" "/register.html" "/privacy-policy.html"; do
    out="$(http_json "GET" "${BASE_URL}${p}")"
    code="$(printf "%s\n" "${out}" | sed -n '1p')"
    append_result "public:${p}" "${code}"
    expect_code "public:${p}" "${code}" "200"
  done

  login_admin "${admin_cookie}"
  assert_admin_session "${admin_cookie}"
  register_verify_login_user "Load Referrer ${RUN_ID}" "${ref_email}" "${ref_phone}" "${ref_password}" "${ref_cookie}"
  register_verify_login_user "Load Buyer A ${RUN_ID}" "${buyer1_email}" "${buyer1_phone}" "${buyer1_password}" "${buyer1_cookie}"
  register_verify_login_user "Load Buyer B ${RUN_ID}" "${buyer2_email}" "${buyer2_phone}" "${buyer2_password}" "${buyer2_cookie}"

  local ref_code="REF${RUN_ID: -6}"
  out="$(http_json "POST" "${BASE_URL}/api/referral/code" "{\"code\":\"${ref_code}\"}" "${ref_cookie}")"
  code="$(printf "%s\n" "${out}" | sed -n '1p')"
  append_result "ref_create_code" "${code}"
  expect_code "ref_create_code" "${code}" "200" "400" "409"
  if [[ "${code}" == "200" ]]; then
    body="$(printf "%s\n" "${out}" | sed -n '2,$p')"
    ref_code="$(printf "%s" "${body}" | json_get "promoCode")"
  fi
  [[ -n "${ref_code}" ]] || fail "Не удалось получить промокод реферала"

  out="$(http_json "PUT" "${BASE_URL}/api/referral/card" '{"cardHolder":"TEST REFERRER","bank":"TEST BANK"}' "${ref_cookie}")"
  code="$(printf "%s\n" "${out}" | sed -n '1p')"
  append_result "ref_bind_sbp" "${code}"
  expect_code "ref_bind_sbp" "${code}" "200"

  local app1 app2
  out="$(http_json "POST" "${BASE_URL}/api/applications" "{\"tariff\":\"PRO\",\"socials\":\"@buyer_a\",\"startDate\":\"2026-05-01\",\"endDate\":\"2026-05-31\",\"promoCode\":\"${ref_code}\"}" "${buyer1_cookie}")"
  code="$(printf "%s\n" "${out}" | sed -n '1p')"
  body="$(printf "%s\n" "${out}" | sed -n '2,$p')"
  append_result "buyer1_create_app" "${code}"
  expect_code "buyer1_create_app" "${code}" "200"
  app1="$(printf "%s" "${body}" | json_get "application.id")"
  [[ -n "${app1}" ]] || fail "Не удалось получить ID первой заявки."

  out="$(http_json "POST" "${BASE_URL}/api/applications" "{\"tariff\":\"PRO\",\"socials\":\"@buyer_b\",\"startDate\":\"2026-06-01\",\"endDate\":\"2026-06-30\",\"promoCode\":\"${ref_code}\"}" "${buyer2_cookie}")"
  code="$(printf "%s\n" "${out}" | sed -n '1p')"
  body="$(printf "%s\n" "${out}" | sed -n '2,$p')"
  append_result "buyer2_create_app" "${code}"
  expect_code "buyer2_create_app" "${code}" "200"
  app2="$(printf "%s" "${body}" | json_get "application.id")"
  [[ -n "${app2}" ]] || fail "Не удалось получить ID второй заявки."

  local aid
  for aid in "${app1}" "${app2}"; do
    assert_admin_session "${admin_cookie}"
    out="$(http_json "PATCH" "${BASE_URL}/api/admin/applications/${aid}/status" '{"status":"Активна"}' "${admin_cookie}")"
    code="$(printf "%s\n" "${out}" | sed -n '1p')"
    append_result "admin_set_active_${aid}" "${code}"
    expect_code "admin_set_active_${aid}" "${code}" "200"

    out="$(http_json "PATCH" "${BASE_URL}/api/admin/applications/${aid}/status" '{"status":"Завершена"}' "${admin_cookie}")"
    code="$(printf "%s\n" "${out}" | sed -n '1p')"
    append_result "admin_set_done_${aid}" "${code}"
    expect_code "admin_set_done_${aid}" "${code}" "200"
  done

  out="$(http_json "POST" "${BASE_URL}/api/referral/withdraw" '{}' "${ref_cookie}")"
  code="$(printf "%s\n" "${out}" | sed -n '1p')"
  append_result "ref_withdraw_request" "${code}"
  expect_code "ref_withdraw_request" "${code}" "200"

  local wq_id
  out="$(http_json "GET" "${BASE_URL}/api/admin/withdrawals?status=pending&page=1&pageSize=50" "" "${admin_cookie}")"
  code="$(printf "%s\n" "${out}" | sed -n '1p')"
  body="$(printf "%s\n" "${out}" | sed -n '2,$p')"
  append_result "admin_get_withdrawals" "${code}"
  expect_code "admin_get_withdrawals" "${code}" "200"
  wq_id="$(printf "%s" "${body}" | json_get "withdrawals.0.id")"
  [[ -n "${wq_id}" ]] || fail "Не найдена pending-заявка на вывод"

  out="$(http_json "PATCH" "${BASE_URL}/api/admin/withdrawals/${wq_id}/status" '{"status":"approved","adminNote":"Одобрено API-suite"}' "${admin_cookie}")"
  code="$(printf "%s\n" "${out}" | sed -n '1p')"
  append_result "admin_approve_withdrawal" "${code}"
  expect_code "admin_approve_withdrawal" "${code}" "200"

  out="$(http_json "GET" "${BASE_URL}/api/admin/users?page=1&pageSize=20" "" "${admin_cookie}")"
  code="$(printf "%s\n" "${out}" | sed -n '1p')"
  append_result "admin_get_users" "${code}"
  expect_code "admin_get_users" "${code}" "200"

  log "OK" "Функциональный API-only прогон завершен."
}

run_heavy_suite() {
  log "ИНФО" "Запуск нагрузочного сценария через tests/load/heavy_scenario.sh"
  BASE_URL="${BASE_URL}" \
  TOTAL_USERS="${HEAVY_TOTAL_USERS}" \
  CONCURRENCY="${HEAVY_CONCURRENCY}" \
  ROUNDS="${HEAVY_ROUNDS}" \
  TIMEOUT_SECONDS="${TIMEOUT_SECONDS}" \
  ORIGIN_HEADER="${ORIGIN_HEADER}" \
  bash "${SCRIPT_DIR}/heavy_scenario.sh"
}

print_summary() {
  [[ -f "${RESULTS_FILE}" ]] || return 0
  echo
  echo "=== API SUITE SUMMARY ==="
  echo "BASE_URL=${BASE_URL}"
  echo "RUN_ID=${RUN_ID}"
  echo "RESULTS_FILE=${RESULTS_FILE}"
  echo
  awk -F '\t' '
  {
    stage=$1;
    code=$2;
    k=stage "|" code;
    by[k]++;
    all[code]++;
  }
  END {
    print "Per stage status distribution:";
    for (k in by) {
      split(k,a,"|");
      printf "  %-30s HTTP %-3s : %d\n", a[1], a[2], by[k];
    }
    print "";
    print "Status totals:";
    for (c in all) {
      printf "  HTTP %-3s : %d\n", c, all[c];
    }
  }' "${RESULTS_FILE}" | sort
}

menu() {
  echo
  echo "Выберите режим теста:"
  echo "  1) Функциональный API-only прогон"
  echo "  2) Нагрузочный прогон (heavy_scenario.sh)"
  printf "Введите номер (1/2): "
  read -r choice
  case "${choice}" in
    1) run_functional_suite ;;
    2) run_heavy_suite ;;
    *) fail "Некорректный выбор. Введите 1 или 2." ;;
  esac
}

main() {
  check_server
  menu
  print_summary
  log "OK" "Тестирование завершено."
}

main "$@"
