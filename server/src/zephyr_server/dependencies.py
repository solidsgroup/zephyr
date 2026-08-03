from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import authenticate_bearer, require_csrf
from .config import Settings, get_settings
from .db import get_db
from .models import User


async def current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    authorization = request.headers.get("Authorization", "")
    if authorization.startswith("Bearer "):
        user = await authenticate_bearer(db, authorization[7:], settings)
        if user is not None and user.active:
            return user
    raw_user_id = request.session.get("user_id")
    if raw_user_id:
        user = await db.get(User, uuid.UUID(raw_user_id))
        if user is not None and user.active:
            require_csrf(request)
            return user
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
