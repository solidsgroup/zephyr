from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime

from authlib.integrations.starlette_client import OAuth
from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings
from .models import ApiToken, User, ensure_utc, utcnow


def configure_oauth(settings: Settings) -> OAuth:
    oauth = OAuth()
    if settings.google_client_id and settings.google_client_secret:
        oauth.register(
            name="google",
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )
    return oauth


def token_digest(token: str, pepper: str) -> str:
    return hmac.new(pepper.encode(), token.encode(), hashlib.sha256).hexdigest()


def issue_api_token() -> tuple[str, str]:
    prefix = secrets.token_hex(4)
    token = f"zph_{prefix}_{secrets.token_urlsafe(32)}"
    return prefix, token


async def authenticate_bearer(db: AsyncSession, token: str, settings: Settings) -> User | None:
    parts = token.split("_", 2)
    if len(parts) != 3 or parts[0] != "zph":
        return None
    record = await db.scalar(select(ApiToken).where(ApiToken.prefix == parts[1]))
    if record is None or record.revoked_at is not None:
        return None
    now = utcnow()
    if record.expires_at is not None and ensure_utc(record.expires_at) < now:
        return None
    if not hmac.compare_digest(record.secret_hash, token_digest(token, settings.token_pepper)):
        return None
    record.last_used_at = now
    await db.commit()
    return await db.get(User, record.user_id)


def require_csrf(request: Request) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    expected = request.session.get("csrf")
    supplied = request.headers.get("X-CSRF-Token")
    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF check failed")


def session_expired(expires_at: datetime | None) -> bool:
    return expires_at is not None and ensure_utc(expires_at) < utcnow()
