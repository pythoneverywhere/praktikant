#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"
VENV_DIR="${ROOT_DIR}/.venv"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo ".env not found. Copying from env.python.example"
  cp "${ROOT_DIR}/env.python.example" "${ENV_FILE}"
  echo "Fill .env (especially POSTGRES_DSN) and run again."
  exit 1
fi

if ! command -v psql >/dev/null 2>&1; then
  echo "psql is not installed. Install PostgreSQL client tools first."
  exit 1
fi

set -a
source "${ENV_FILE}"
set +a

if [[ -z "${POSTGRES_DSN:-}" ]]; then
  echo "POSTGRES_DSN is empty in .env"
  exit 1
fi

PARSED="$(python3 - <<'PY'
import os
from urllib.parse import urlparse, unquote

dsn = os.environ["POSTGRES_DSN"].replace("+psycopg", "")
parsed = urlparse(dsn)
db = parsed.path.lstrip("/") or "praktikant"
host = parsed.hostname or "localhost"
port = parsed.port or 5432
user = unquote(parsed.username or "postgres")
password = unquote(parsed.password or "")
print(host)
print(port)
print(user)
print(password)
print(db)
PY
)"

DB_HOST="$(printf "%s\n" "${PARSED}" | sed -n '1p')"
DB_PORT="$(printf "%s\n" "${PARSED}" | sed -n '2p')"
DB_USER="$(printf "%s\n" "${PARSED}" | sed -n '3p')"
DB_PASSWORD="$(printf "%s\n" "${PARSED}" | sed -n '4p')"
DB_NAME="$(printf "%s\n" "${PARSED}" | sed -n '5p')"

export PGPASSWORD="${DB_PASSWORD}"

echo "Checking PostgreSQL connection as '${DB_USER}' on ${DB_HOST}:${DB_PORT} ..."
if ! psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d postgres -tAc "SELECT 1" >/dev/null; then
  echo "ERROR: cannot connect to PostgreSQL with credentials from POSTGRES_DSN."
  echo "Check .env -> POSTGRES_DSN user/password/host/port."
  echo "Current DSN user='${DB_USER}', host='${DB_HOST}', port='${DB_PORT}', db='${DB_NAME}'."
  exit 1
fi

echo "Checking database '${DB_NAME}' ..."
EXISTS="$(psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'")"
if [[ "${EXISTS}" != "1" ]]; then
  echo "Creating database '${DB_NAME}' ..."
  createdb -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" "${DB_NAME}"
else
  echo "Database '${DB_NAME}' already exists."
fi

export PYTHONPATH="${ROOT_DIR}:${PYTHONPATH:-}"
if [[ ! -d "${VENV_DIR}" ]]; then
  python3 -m venv "${VENV_DIR}"
fi
PY_BIN="${VENV_DIR}/bin/python"
source "${VENV_DIR}/bin/activate"
python -m pip install --upgrade pip
python -m pip install -r "${ROOT_DIR}/requirements.txt"

echo "Applying Alembic migrations ..."
(
  cd "${ROOT_DIR}"
  "${PY_BIN}" - <<'PY'
from app.db.init_db import init_db

init_db()
print("Database schema is ready.")
PY
)

echo "Done."
