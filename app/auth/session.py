from __future__ import annotations

from dataclasses import dataclass

from itsdangerous import URLSafeTimedSerializer
from starlette.responses import Response

from app.auth.config import auth_settings

SESSION_COOKIE_NAME = "ibkr_session"


@dataclass
class AuthUser:
    sub: str  # Google user ID
    email: str
    name: str
    picture: str


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(auth_settings.session_secret)


def create_session(user: AuthUser) -> str:
    return _serializer().dumps({"sub": user.sub, "email": user.email, "name": user.name, "picture": user.picture})


def verify_session(token: str) -> AuthUser | None:
    try:
        data = _serializer().loads(token, max_age=auth_settings.session_max_age_seconds)
        return AuthUser(**data)
    except Exception:
        return None


def _is_localhost() -> bool:
    return auth_settings.oauth_redirect_url.startswith("http://localhost")


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=auth_settings.session_max_age_seconds,
        httponly=True,
        secure=not _is_localhost(),
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")


def get_current_user(request) -> AuthUser | None:
    """Get the authenticated user from request state (set by AuthMiddleware)."""
    return getattr(request.state, "user", None)
