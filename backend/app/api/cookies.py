"""The session cookie: the only place the raw token is handed out (R3.AC1, R12.AC8)."""

from fastapi import Response

from app.config import get_settings
from app.platform.identity.api import SessionToken


def set_session_cookie(response: Response, token: SessionToken) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token.raw,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(key=settings.session_cookie_name, path="/")
