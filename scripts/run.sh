#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
ENV_FILE="${ROOT_DIR}/.env"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "No .env found. Creating from env.python.example"
  cp "${ROOT_DIR}/env.python.example" "${ENV_FILE}"
  echo "Fill .env before production run."
fi

set -a
source "${ENV_FILE}"
set +a

if [[ ! -d "${VENV_DIR}" ]]; then
  python3 -m venv "${VENV_DIR}"
fi

source "${VENV_DIR}/bin/activate"
python -m pip install --upgrade pip
python -m pip install -r "${ROOT_DIR}/requirements.txt"

cd "${ROOT_DIR}"
export PYTHONPATH="${ROOT_DIR}:${PYTHONPATH:-}"

PORT="$(python - <<'PY'
import os
print(os.getenv("APP_PORT") or os.getenv("PORT") or "8000")
PY
)"
export APP_PORT="${PORT}"

if ! python - <<'PY'
from sqlalchemy import create_engine, text

from app.core.config import get_settings

dsn = get_settings().postgres_dsn
engine = create_engine(dsn, pool_pre_ping=True, connect_args={"connect_timeout": 3})
try:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
except Exception as exc:  # noqa: BLE001
    print(f"ERROR: cannot connect to PostgreSQL ({exc})")
    raise SystemExit(1)
PY
then
  echo "PostgreSQL is unavailable. Start DB first or fix POSTGRES_DSN in .env"
  exit 1
fi

echo "Applying database migrations (alembic upgrade head) ..."
if ! python - <<'PY'
from app.db.init_db import init_db

init_db()
PY
then
  echo "Failed to apply database migrations."
  exit 1
fi

APP_ENV_LOWER="$(printf '%s' "${APP_ENV:-development}" | tr '[:upper:]' '[:lower:]')"
if [[ "${APP_ENV_LOWER}" == "production" || "${APP_ENV_LOWER}" == "prod" ]]; then
  # В проде слушаем только localhost — наружу сервис публикует nginx (TLS + TRUSTED_PROXIES=127.0.0.1).
  HOST="${APP_HOST:-127.0.0.1}"
  echo "Starting backend (production) on ${HOST}:${PORT}"
  exec uvicorn app.main:app --host "${HOST}" --port "${PORT}" --no-server-header
fi

HOST="${APP_HOST:-127.0.0.1}"
echo "Starting backend (development) on http://${HOST}:${PORT}"
exec uvicorn app.main:app --host "${HOST}" --port "${PORT}" --reload
