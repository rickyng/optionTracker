from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


async def get_or_create_user(
    db: AsyncSession,
    *,
    google_sub: str,
    email: str,
    name: str,
    picture: str,
) -> User:
    """Upsert user by google_sub. Creates if new, updates name/picture if changed."""
    result = await db.execute(select(User).where(User.google_sub == google_sub))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(google_sub=google_sub, email=email, name=name, picture=picture)
        db.add(user)
    else:
        user.email = email
        user.name = name
        user.picture = picture

    await db.commit()
    await db.refresh(user)
    return user


async def get_user_by_sub(db: AsyncSession, google_sub: str) -> User | None:
    result = await db.execute(select(User).where(User.google_sub == google_sub))
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: int) -> User | None:
    return await db.get(User, user_id)
