LOAD TESTS (BASH)

Files:
- tests/load/run_service_tests.sh
  Единый интерактивный скрипт с меню:
  1) Полный функциональный прогон ключевых сценариев.
  2) Масштабный нагрузочный тест (много пользователей, массовые записи/обработки).
  Важно: скрипт не использует endpoints с реальной отправкой email-кодов, чтобы не тратить API.

- tests/load/heavy_scenario.sh
  Full scenario with writes + auth + authenticated reads.
  Simulates many users in parallel:
  register -> email confirm -> login/step-up -> /api/me + /api/my/subscription.

- tests/load/read_burst.sh
  High-concurrency read-only burst for static/public endpoints.

Quick start:
1) Start server:
   npm run start

2) Run unified test script:
   bash tests/load/run_service_tests.sh

3) (Optional) Run legacy read burst:
   bash tests/load/read_burst.sh

4) (Optional) Run legacy heavy scenario:
   bash tests/load/heavy_scenario.sh

Tuning via env:
- BASE_URL (default: http://localhost:3000)
- SCALE_USERS (unified mode 2 only, default: 1200)
- CONCURRENCY (unified mode 2 default: 120)
- TOTAL_USERS (heavy scenario only, default: 60)
- CONCURRENCY (legacy scripts: default 12 for heavy, 50 for read burst)
- ROUNDS (heavy scenario only, default: 6)
- REQUESTS (read burst only, default: 2000)
- TIMEOUT_SECONDS

Important:
- In heavy scenario, 429 statuses are expected under high pressure because rate limiting is enabled.
- Heavy scenario uses test code 335335 for email confirmation and step-up verification.
- If you configure real email provider limits, mail-related steps can become bottlenecks.

