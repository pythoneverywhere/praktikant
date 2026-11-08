import asyncio
import contextlib
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.staticfiles import StaticFiles

from app.api.routes import router as api_router
from app.core.config import get_settings
from app.db.init_db import init_db
from app.tasks.autocomplete import run_autocomplete_loop

settings = get_settings()
ROOT = Path(__file__).resolve().parents[1]

PUBLIC_FILES = {
    "index.html",
    "login.html",
    "register.html",
    "cabinet.html",
    "apply.html",
    "admin.html",
    "auth.js",
    "theme.js",
    "theme.css",
    "verify-email.html",
    "reset-password.html",
    "privacy-policy.html",
}


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.run_db_migrations_on_startup:
        init_db()
    task = asyncio.create_task(run_autocomplete_loop(settings))
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


# Swagger/OpenAPI доступны только вне production.
_docs_enabled = not settings.is_production
app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)

CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        # Страницы используют inline-скрипты/стили; внешние источники запрещены.
        "script-src 'self' 'unsafe-inline'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob:",
        "font-src 'self' data:",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(_request: Request, exc: StarletteHTTPException):
    return JSONResponse(status_code=exc.status_code, content={"error": str(exc.detail)}, headers=exc.headers)


FIELD_LABELS = {
    "name": "Имя",
    "email": "Email",
    "newEmail": "Email",
    "phone": "Телефон",
    "password": "Пароль",
    "newPassword": "Новый пароль",
    "socials": "Соцсети",
    "note": "Комментарий",
    "adminNote": "Комментарий",
}


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_request: Request, exc: RequestValidationError):
    errors = exc.errors()
    if not errors:
        return JSONResponse(status_code=422, content={"error": "Некорректный запрос"})
    first = errors[0]
    field = str(first.get("loc", [""])[-1])
    label = FIELD_LABELS.get(field, field)
    err_type = first.get("type", "")
    ctx = first.get("ctx") or {}
    if err_type == "string_too_long":
        message = f"{label}: слишком длинное значение (максимум {ctx.get('max_length')} символов)"
    elif err_type == "string_too_short":
        message = f"{label}: слишком короткое значение (минимум {ctx.get('min_length')} символов)"
    elif field in {"email", "newEmail"} and err_type == "value_error":
        message = "Введите корректный email"
    else:
        message = str(first.get("msg", "Некорректный запрос"))
    return JSONResponse(status_code=422, content={"error": message})


@app.exception_handler(IntegrityError)
async def integrity_exception_handler(_request: Request, _exc: IntegrityError):
    return JSONResponse(status_code=409, content={"error": "Конфликт данных: значение уже используется"})


@app.middleware("http")
async def csrf_origin_guard(request: Request, call_next):
    if not request.url.path.startswith("/api/"):
        return await call_next(request)
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return await call_next(request)

    host = request.headers.get("host", "")
    origin = request.headers.get("origin", "")
    referer = request.headers.get("referer", "")

    def same_host(raw_url: str) -> bool:
        if not raw_url:
            return False
        try:
            return urlparse(raw_url).netloc == host
        except Exception:  # noqa: BLE001
            return False

    if (origin and same_host(origin)) or ((not origin) and referer and same_host(referer)):
        return await call_next(request)
    return JSONResponse(status_code=403, content={"error": "CSRF-защита: некорректный источник запроса"})


@app.middleware("http")
async def hide_sensitive_paths(request: Request, call_next):
    path = request.url.path
    blocked_prefixes = ("/data", "/node_modules", "/.git")
    blocked_files = {"/.env", "/server.js", "/package.json", "/package-lock.json", "/env.example.txt"}
    if path.startswith(blocked_prefixes) or path in blocked_files or path.startswith("/.env."):
        return JSONResponse(status_code=404, content={"error": "Not found"})
    return await call_next(request)


# Добавлен последним => внешний слой: заголовки получают и ответы других middleware (403/404).
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    if settings.cookie_secure_effective:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


app.include_router(api_router)


@app.get("/")
async def root() -> FileResponse:
    return FileResponse(ROOT / "index.html")


@app.get("/{filename}")
async def static_pages(filename: str):
    if filename not in PUBLIC_FILES:
        return JSONResponse(status_code=404, content={"error": "Not found"})
    path = ROOT / filename
    if not path.exists():
        return JSONResponse(status_code=404, content={"error": "Not found"})
    return FileResponse(path)


app.mount("/immages", StaticFiles(directory=ROOT / "immages"), name="immages")
app.mount("/doc", StaticFiles(directory=ROOT / "doc"), name="doc")
