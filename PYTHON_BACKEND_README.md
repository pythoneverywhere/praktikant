# Python Backend (FastAPI + PostgreSQL)

## Что сделано
- Монолитный backend перенесен на Python (`FastAPI`) с модульной архитектурой.
- Слои: `api` -> `services` -> `repositories` -> `models`.
- PostgreSQL через `SQLAlchemy`.
- Добавлены OOP-подходы и паттерны:
  - `Repository pattern`;
  - `Service layer`;
  - `Factory pattern` для email-провайдера.

## Запуск
```bash
bash scripts/run_backend.sh
```

## Важные env-переменные
- `POSTGRES_DSN`
- `JWT_SECRET` (минимум 32 символа)
- `APP_PORT`
- `APP_BASE_URL`
- `ADMIN_EMAILS`

Шаблон: `env.python.example`.
