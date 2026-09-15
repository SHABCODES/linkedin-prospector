"""
app/main.py
FastAPI application entry point.
Registers routers, configures logging, initialises the database on startup,
and serves the static HTML dashboard.
"""
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import init_db

settings = get_settings()

# ── Structured logging ──────────────────────────────────────────────────────────
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.dev.ConsoleRenderer() if settings.app_env == "development"
        else structlog.processors.JSONRenderer(),
    ]
)

log = structlog.get_logger(__name__)


# ── Lifespan ────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("startup.init_db")
    await init_db()
    mode = "MOCK" if settings.mock_mode else "PROXYCURL"
    llm = "GEMINI" if settings.llm_enabled else "RULES-BASED"
    log.info("startup.ready", data_mode=mode, llm_mode=llm)
    yield
    log.info("shutdown.complete")


# ── App ─────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="LinkedIn Prospecting & Research Assistant",
    description=(
        "AI-powered LinkedIn prospect discovery, enrichment, qualification, "
        "and personalised outreach copy generation. Part of the viamagus GTM portfolio."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ─────────────────────────────────────────────────────────────────────
from app.api import search, prospects, export, metrics  # noqa: E402

app.include_router(search.router, prefix="/api")
app.include_router(prospects.router, prefix="/api")
app.include_router(export.router, prefix="/api")
app.include_router(metrics.router, prefix="/api")

# ── Static files (dashboard) ────────────────────────────────────────────────────
import os  # noqa: E402

static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/", include_in_schema=False)
async def serve_dashboard():
    return FileResponse(os.path.join(static_dir, "index.html"))


# ── Health check ────────────────────────────────────────────────────────────────
@app.get("/api/health", tags=["system"])
async def health():
    return {
        "status": "ok",
        "mock_mode": settings.mock_mode,
        "llm_enabled": settings.llm_enabled,
        "gemini_model": settings.gemini_model if settings.llm_enabled else None,
    }

