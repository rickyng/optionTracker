from fastapi import APIRouter, Request

from app.auth.session import get_current_user

router = APIRouter(prefix="/api", tags=["user"])


@router.get("/me")
async def get_me(request: Request):
    """Return current user info for the dashboard user menu."""
    user = get_current_user(request)
    if not user:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "name": user.name,
        "email": user.email,
        "picture": user.picture,
        "sub": user.sub,
    }
