"""Pure ASGI auth middleware.

Avoids BaseHTTPMiddleware which is known to cause issues with WSGI-mounted
sub-applications (e.g. Dash). The coroutine/iterator errors on
POST /dashboard/_dash-update-component were caused by BaseHTTPMiddleware's
call_next wrapping conflicting with WSGI body streams.
"""

from app.auth.config import auth_settings
from app.auth.session import SESSION_COOKIE_NAME, AuthUser, verify_session

PUBLIC_PATHS = {"/health", "/auth/login", "/auth/callback", "/auth/logout", "/auth/unauthorized"}
PUBLIC_PREFIXES = ("/auth/",)
INTERNAL_API_KEY_HEADER = "X-Internal-API-Key"
USER_SUB_HEADER = "X-User-Sub"


class AuthMiddleware:
    """Pure ASGI auth middleware — no BaseHTTPMiddleware, no call_next."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        if scope["type"] == "websocket":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        headers = _parse_headers(scope)

        # Allow public paths
        if path in PUBLIC_PATHS or any(path.startswith(p) for p in PUBLIC_PREFIXES):
            await self.app(scope, receive, send)
            return

        # Allow Dash static assets and internal Dash AJAX endpoints
        if path.startswith("/dashboard/assets/") or path.startswith("/dashboard/_dash-"):
            await self.app(scope, receive, send)
            return

        # Allow internal requests (Dash callbacks → API) via shared secret
        internal_key = headers.get(INTERNAL_API_KEY_HEADER.lower())
        if internal_key and internal_key == auth_settings.internal_api_key:
            user_sub = headers.get(USER_SUB_HEADER.lower())
            if user_sub:
                scope.setdefault("state", {})
                scope["state"]["user"] = AuthUser(sub=user_sub, email="", name="", picture="")
            await self.app(scope, receive, send)
            return

        # Check session cookie
        cookie_header = headers.get("cookie", "")
        token = _extract_cookie(cookie_header, SESSION_COOKIE_NAME)
        if token:
            user = verify_session(token)
            if user:
                scope.setdefault("state", {})
                scope["state"]["user"] = user
                await self.app(scope, receive, send)
                return

        # Unauthenticated — send response directly
        if path.startswith("/api/"):
            await _send_json(send, 401, {"error": "Authentication required"})
        else:
            await _send_redirect(send, "/auth/login")


def _parse_headers(scope: dict) -> dict[str, str]:
    """Parse raw ASGI headers into a lowercase-keyed dict."""
    return {key.decode().lower(): value.decode() for key, value in scope.get("headers", [])}


def _extract_cookie(cookie_header: str, name: str) -> str | None:
    """Parse a specific cookie value from the Cookie header string."""
    for part in cookie_header.split(";"):
        part = part.strip()
        if part.startswith(f"{name}="):
            return part[len(name) + 1 :]
    return None


async def _send_json(send, status_code: int, body: dict) -> None:
    """Send a JSON response directly via ASGI send."""
    import json

    raw = json.dumps(body).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                [b"content-type", b"application/json"],
                [b"content-length", str(len(raw)).encode()],
            ],
        }
    )
    await send({"type": "http.response.body", "body": raw})


async def _send_redirect(send, location: str) -> None:
    """Send a 302 redirect directly via ASGI send."""
    await send(
        {
            "type": "http.response.start",
            "status": 302,
            "headers": [
                [b"location", location.encode()],
                [b"content-length", b"0"],
            ],
        }
    )
    await send({"type": "http.response.body", "body": b""})
