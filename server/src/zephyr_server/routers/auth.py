from __future__ import annotations

import secrets
import uuid
from datetime import timedelta
from typing import cast
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from ..auth import configure_oauth, issue_api_token, token_digest
from ..config import Settings, get_settings
from ..db import get_db
from ..dependencies import current_user
from ..models import ApiToken, DeviceAuthorization, User, ensure_utc, utcnow
from ..schemas import (
    DeviceApprovalRead,
    DeviceAuthorizationCreate,
    DeviceAuthorizationCreated,
    DeviceTokenExchange,
    DeviceTokenResult,
    TokenCreate,
    TokenCreated,
    TokenRead,
    UserRead,
)

router = APIRouter(prefix="/auth", tags=["authentication"])
DEVICE_CODE_SEPARATOR = "."


def safe_login_next(value: str | None) -> str:
    if not value:
        return "/"
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        return "/"
    if not parsed.path.startswith("/connect/") or parsed.path.startswith("//"):
        return "/"
    return parsed.path


def encoded_device_code(record_id: uuid.UUID, secret: str) -> str:
    return f"{record_id}{DEVICE_CODE_SEPARATOR}{secret}"


def parsed_device_code(value: str) -> tuple[uuid.UUID, str] | None:
    try:
        raw_id, secret = value.split(DEVICE_CODE_SEPARATOR, 1)
        record_id = uuid.UUID(raw_id)
    except (ValueError, AttributeError):
        return None
    if not secret:
        return None
    return record_id, secret


async def device_record(
    db: AsyncSession,
    code: str,
    secret_field: str,
    settings: Settings,
) -> DeviceAuthorization | None:
    parsed = parsed_device_code(code)
    if parsed is None:
        return None
    record_id, secret = parsed
    record = await db.scalar(
        select(DeviceAuthorization).where(DeviceAuthorization.id == record_id).with_for_update()
    )
    if record is None:
        return None
    expected = getattr(record, secret_field)
    if not secrets.compare_digest(expected, token_digest(secret, settings.token_pepper)):
        return None
    return record


@router.get("/login")
async def login(
    request: Request,
    next_path: str | None = Query(default=None, alias="next"),
    settings: Settings = Depends(get_settings),
) -> Response:
    oauth = configure_oauth(settings)
    google = oauth.create_client("google")
    if google is None:
        raise HTTPException(status_code=503, detail="Google login is not configured")
    request.session["login_next"] = safe_login_next(next_path)
    redirect_uri = f"{settings.public_url.rstrip('/')}/api/v1/auth/callback/google"
    return cast(Response, await google.authorize_redirect(request, redirect_uri))


@router.get("/callback/google")
async def google_callback(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    oauth = configure_oauth(settings)
    google = oauth.create_client("google")
    if google is None:
        raise HTTPException(status_code=503, detail="Google login is not configured")
    token = await google.authorize_access_token(request)
    info = token.get("userinfo") or await google.userinfo(token=token)
    email = str(info.get("email", "")).lower()
    if not info.get("email_verified"):
        raise HTTPException(status_code=403, detail="Google email is not verified")
    if info.get("hd") != settings.google_allowed_domain or not email.endswith(
        f"@{settings.google_allowed_domain}"
    ):
        raise HTTPException(status_code=403, detail="A solids.group Google account is required")

    user = await db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email)
        db.add(user)
    user.name = str(info.get("name", ""))
    user.picture_url = info.get("picture")
    user.google_subject = str(info.get("sub", ""))
    await db.commit()
    await db.refresh(user)
    request.session["user_id"] = str(user.id)
    request.session["csrf"] = secrets.token_urlsafe(24)
    return RedirectResponse(safe_login_next(request.session.pop("login_next", "/")))


@router.post("/dev-login", response_model=UserRead)
async def dev_login(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    if not settings.dev_auth or settings.env == "production":
        raise HTTPException(status_code=404, detail="Not found")
    email = f"developer@{settings.google_allowed_domain}"
    user = await db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, name="Zephyr Developer", google_subject="development")
        db.add(user)
        await db.commit()
        await db.refresh(user)
    request.session["user_id"] = str(user.id)
    request.session["csrf"] = secrets.token_urlsafe(24)
    return user


@router.post("/logout", status_code=204)
async def logout(request: Request) -> None:
    request.session.clear()


@router.get("/me")
async def me(request: Request, user: User = Depends(current_user)) -> dict[str, object]:
    return {"user": UserRead.model_validate(user), "csrf_token": request.session.get("csrf")}


@router.get("/tokens", response_model=list[TokenRead])
async def list_tokens(
    user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
) -> list[ApiToken]:
    return list(
        await db.scalars(
            select(ApiToken).where(ApiToken.user_id == user.id).order_by(ApiToken.created_at.desc())
        )
    )


@router.post("/tokens", response_model=TokenCreated, status_code=status.HTTP_201_CREATED)
async def create_token(
    payload: TokenCreate,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TokenCreated:
    prefix, plaintext = issue_api_token()
    record = ApiToken(
        user_id=user.id,
        name=payload.name,
        prefix=prefix,
        secret_hash=token_digest(plaintext, settings.token_pepper),
        expires_at=payload.expires_at,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return TokenCreated(**TokenRead.model_validate(record).model_dump(), token=plaintext)


@router.delete("/tokens/{token_id}", status_code=204)
async def revoke_token(
    token_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    token = await db.get(ApiToken, token_id)
    if token is None or token.user_id != user.id:
        raise HTTPException(status_code=404, detail="Token not found")
    token.revoked_at = utcnow()
    await db.commit()


@router.post("/device", response_model=DeviceAuthorizationCreated, status_code=201)
async def create_device_authorization(
    payload: DeviceAuthorizationCreate,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DeviceAuthorizationCreated:
    now = utcnow()
    await db.execute(
        delete(DeviceAuthorization).where(DeviceAuthorization.expires_at < now - timedelta(days=1))
    )
    device_secret = secrets.token_urlsafe(32)
    browser_secret = secrets.token_urlsafe(32)
    record = DeviceAuthorization(
        device_name=payload.device_name,
        device_secret_hash=token_digest(device_secret, settings.token_pepper),
        browser_secret_hash=token_digest(browser_secret, settings.token_pepper),
        expires_at=now + timedelta(seconds=settings.device_login_ttl_seconds),
    )
    db.add(record)
    await db.commit()
    return DeviceAuthorizationCreated(
        device_code=encoded_device_code(record.id, device_secret),
        verification_url=(
            f"{settings.public_url.rstrip('/')}/connect/"
            f"{encoded_device_code(record.id, browser_secret)}"
        ),
        expires_in=settings.device_login_ttl_seconds,
        interval=settings.device_login_poll_interval_seconds,
    )


@router.post("/device/{browser_code}/approve", response_model=DeviceApprovalRead)
async def approve_device_authorization(
    browser_code: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DeviceApprovalRead:
    record = await device_record(db, browser_code, "browser_secret_hash", settings)
    if record is None:
        raise HTTPException(status_code=404, detail="Login request not found")
    if ensure_utc(record.expires_at) < utcnow():
        raise HTTPException(status_code=410, detail="Login request expired")
    if record.consumed_at is not None:
        raise HTTPException(status_code=409, detail="Login request was already used")
    if record.user_id is not None and record.user_id != user.id:
        raise HTTPException(status_code=409, detail="Login request was already approved")
    record.user_id = user.id
    record.approved_at = utcnow()
    await db.commit()
    return DeviceApprovalRead(status="approved", device_name=record.device_name)


@router.post("/device/token", response_model=DeviceTokenResult)
async def exchange_device_authorization(
    payload: DeviceTokenExchange,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DeviceTokenResult:
    record = await device_record(db, payload.device_code, "device_secret_hash", settings)
    if record is None:
        raise HTTPException(status_code=404, detail="Login request not found")
    if ensure_utc(record.expires_at) < utcnow():
        return DeviceTokenResult(status="expired")
    if record.consumed_at is not None:
        return DeviceTokenResult(status="consumed")
    if record.approved_at is None or record.user_id is None:
        return DeviceTokenResult(status="pending")
    user = await db.get(User, record.user_id)
    if user is None or not user.active:
        raise HTTPException(status_code=403, detail="Approving account is unavailable")
    prefix, plaintext = issue_api_token()
    db.add(
        ApiToken(
            user_id=user.id,
            name=f"zph · {record.device_name}",
            prefix=prefix,
            secret_hash=token_digest(plaintext, settings.token_pepper),
        )
    )
    record.consumed_at = utcnow()
    await db.commit()
    return DeviceTokenResult(status="approved", token=plaintext, email=user.email)
