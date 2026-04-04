from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.auth.config import auth_settings
from app.auth.oauth import oauth
from app.auth.session import (
    SESSION_COOKIE_NAME,
    AuthUser,
    clear_session_cookie,
    create_session,
    set_session_cookie,
    verify_session,
)
from app.database import async_session

router = APIRouter(prefix="/auth", tags=["auth"])

_LOGIN_HTML = """<!DOCTYPE html>
<html>
<head><title>IBKR Options Analyzer — Sign In</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         background: #12121f; color: #e0e0e0; display: flex; justify-content: center;
         align-items: center; min-height: 100vh; margin: 0; }}
  .card {{ background: #1a1a2e; border: 1px solid #2a2a4a; border-radius: 12px;
           padding: 3rem; text-align: center; max-width: 400px; }}
  h1 {{ font-size: 1.5rem; font-weight: 700; margin-bottom: 0.5rem; }}
  p {{ color: #888; margin-bottom: 2rem; font-size: 0.9rem; }}
  a.btn {{ display: inline-block; background: #4285f4; color: #fff; padding: 12px 32px;
           border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 1rem; }}
  a.btn:hover {{ background: #3367d6; }}
</style></head>
<body>
  <div class="card">
    <h1>IBKR Options Analyzer</h1>
    <p>Sign in with your Google account to continue.</p>
    <a class="btn" href="/auth/login">Sign in with Google</a>
  </div>
</body>
</html>"""

_UNAUTHORIZED_HTML = """<!DOCTYPE html>
<html>
<head><title>Access Denied</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         background: #12121f; color: #e0e0e0; display: flex; justify-content: center;
         align-items: center; min-height: 100vh; margin: 0; }}
  .card {{ background: #1a1a2e; border: 1px solid #2a2a4a; border-radius: 12px;
           padding: 3rem; text-align: center; max-width: 400px; }}
  h1 {{ font-size: 1.5rem; color: #e74c3c; margin-bottom: 1rem; }}
  p {{ color: #888; margin-bottom: 2rem; }}
  a {{ color: #4285f4; }}
</style></head>
<body>
  <div class="card">
    <h1>Access Denied</h1>
    <p>Your Google account is not authorized to use this application.</p>
    <a href="/auth/login">Try a different account</a>
  </div>
</body>
</html>"""


@router.get("/login")
async def login(request: Request):
    # If already authenticated, redirect to dashboard
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token and verify_session(token):
        return RedirectResponse("/dashboard/")

    if not auth_settings.google_client_id:
        return HTMLResponse("Auth is not configured.", status_code=500)

    google = oauth.create_client("google")
    return await google.authorize_redirect(request, auth_settings.oauth_redirect_url)


@router.get("/callback")
async def callback(request: Request):
    google = oauth.create_client("google")
    token = await google.authorize_access_token(request)
    userinfo = token.get("userinfo")

    if not userinfo:
        return RedirectResponse("/auth/login")

    # Phase 1: optional email allowlist
    if auth_settings.allowed_emails:
        allowed = {e.strip().lower() for e in auth_settings.allowed_emails.split(",")}
        if userinfo["email"].lower() not in allowed:
            return HTMLResponse(_UNAUTHORIZED_HTML, status_code=403)

    user = AuthUser(
        sub=userinfo["sub"],
        email=userinfo["email"],
        name=userinfo.get("name", ""),
        picture=userinfo.get("picture", ""),
    )

    # Persist/update user in database
    async with async_session() as db:
        from app.services.user_service import get_or_create_user

        await get_or_create_user(
            db,
            google_sub=user.sub,
            email=user.email,
            name=user.name,
            picture=user.picture,
        )

    session_token = create_session(user)
    response = RedirectResponse("/dashboard/")
    set_session_cookie(response, session_token)
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse("/auth/login")
    clear_session_cookie(response)
    return response


@router.get("/unauthorized")
async def unauthorized():
    return HTMLResponse(_UNAUTHORIZED_HTML, status_code=403)
