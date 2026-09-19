"""Зависимости FastAPI: контекст приложения и текущий пользователь."""
from __future__ import annotations

from fastapi import Header, Query, Request

from app.services.common import AppContext
from app.services.projects import user_from_token


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx


def current_user(request: Request, authorization: str | None = Header(default=None),
                 token: str | None = Query(default=None)) -> int:
    """Токен из заголовка ``Authorization: Bearer …`` или из ``?token=`` (для <img src>)."""
    raw = token
    if authorization and authorization.lower().startswith("bearer "):
        raw = authorization[7:].strip()
    return user_from_token(request.app.state.ctx, raw)
