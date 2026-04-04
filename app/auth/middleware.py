from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse

from app.auth.config import auth_settings
from app.auth.session import SESSION_COOKIE_NAME, AuthUser, verify_session

PUBLIC_PATHS = {"/health", "/auth/login", "/auth/callback", "/auth/logout", "/auth/unauthorized"}
PUBLIC_PREFIXES = ("/auth/",)
INTERNAL_API_KEY_HEADER = "X-Internal-API-Key"
USER_SUB_HEADER = "X-User-Sub"


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Allow public paths
        if path in PUBLIC_PATHS or any(path.startswith(p) for p in PUBLIC_PREFIXES):
            return await call_next(request)

        # Allow Dash static assets and internal Dash AJAX endpoints
        if path.startswith("/dashboard/assets/"):
            return await call_next(request)
        if path.startswith("/dashboard/_dash-"):
            return await call_next(request)

        # Allow internal requests (Dash callbacks → API) via shared secret
        internal_key = request.headers.get(INTERNAL_API_KEY_HEADER)
        if internal_key and internal_key == auth_settings.internal_api_key:
            # If X-User-Sub header is also present, set user identity
            user_sub = request.headers.get(USER_SUB_HEADER)
            if user_sub:
                request.state.user = AuthUser(sub=user_sub, email="", name="", picture="")
            return await call_next(request)

        # Check session cookie
        token = request.cookies.get(SESSION_COOKIE_NAME)
        if token:
            user = verify_session(token)
            if user:
                request.state.user = user
                return await call_next(request)

        # Unauthenticated
        if path.startswith("/api/"):
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        return RedirectResponse("/auth/login")
