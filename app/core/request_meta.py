from fastapi import Request

from app.core.config import get_settings


def _peer_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _from_trusted_proxy(request: Request) -> bool:
    return _peer_ip(request) in get_settings().trusted_proxy_set()


def get_client_ip(request: Request) -> str:
    """IP клиента. X-Forwarded-For учитывается только от доверенного прокси (TRUSTED_PROXIES)."""
    if _from_trusted_proxy(request):
        # Берём крайний правый адрес, который добавил наш прокси (левые клиент может подделать).
        parts = [p.strip() for p in (request.headers.get("x-forwarded-for") or "").split(",") if p.strip()]
        if parts:
            return parts[-1][:64]
        real_ip = (request.headers.get("x-real-ip") or "").strip()
        if real_ip:
            return real_ip[:64]
    return _peer_ip(request)


def get_client_country(request: Request) -> str:
    if not _from_trusted_proxy(request):
        return "UNKNOWN"
    value = (request.headers.get("cf-ipcountry") or request.headers.get("x-country-code") or "UNKNOWN").upper()
    return value[:16]


def get_device_fingerprint(request: Request) -> str:
    value = (request.headers.get("x-device-fingerprint") or "").strip()
    return value[:200]
