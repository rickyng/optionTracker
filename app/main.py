from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.api.accounts import router as accounts_router
from app.api.dashboard import router as dashboard_router
from app.api.flex import router as flex_router
from app.api.import_csv import router as import_router
from app.api.me import router as me_router
from app.api.positions import router as positions_router
from app.api.prices import router as prices_router
from app.api.reports import router as reports_router
from app.api.strategies import router as strategies_router
from app.auth.config import auth_settings
from app.auth.routes import router as auth_router
from app.database import async_session, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="IBKR Options Analyzer",
    version="2.0.0",
    lifespan=lifespan,
)

# Gzip compression for API responses
app.add_middleware(GZipMiddleware, minimum_size=500)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth middleware — only active when Google credentials are configured
if auth_settings.google_client_id:
    from app.auth.middleware import AuthMiddleware

    # SessionMiddleware is required by Authlib for OAuth state storage
    app.add_middleware(SessionMiddleware, secret_key=auth_settings.session_secret)
    app.add_middleware(AuthMiddleware)

app.include_router(auth_router)
app.include_router(me_router)
app.include_router(accounts_router)
app.include_router(positions_router)
app.include_router(strategies_router)
app.include_router(import_router)
app.include_router(flex_router)
app.include_router(prices_router)
app.include_router(reports_router)
app.include_router(dashboard_router)

# Mount Dash dashboard
from app.dashboard.app import create_dash_app

dash_app = create_dash_app(app)


@app.get("/health")
async def health():
    async with async_session() as session:
        await session.execute(text("SELECT 1"))
    return {"status": "ok", "db": "connected"}
