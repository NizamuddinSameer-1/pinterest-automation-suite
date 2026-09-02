"""
Pinterest Realism Engine (PRE) — Main FastAPI Backend Application.

Connects all pipeline routes, database lifecycle, static image delivery,
and real-time Obsidian Vault synchronization.
"""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import amazon, debug, generation, jobs, library, lookbooks, pins, products, references
from app.config import settings
from app.database import init_db
from app.services.error_diagnostics import record_diagnostic_error

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("pre.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Bootstrap storage directories, database tables, and the pin scheduler."""
    logger.info("Initializing storage directories...")
    settings.ensure_storage_dirs()

    logger.info("Bootstrapping SQLite database...")
    await init_db()

    # The scheduling queue previously had no consumer at all. Starting the loop
    # here also runs a catch-up sweep, so pins that came due while the app was
    # closed publish on the next tick instead of being stranded.
    from app.services.scheduler import start_scheduler, stop_scheduler
    start_scheduler()

    # Recover any generation jobs stranded in GENERATING if the server was restarted
    try:
        from app.database import async_session
        from app.services.job_reaper import reap_stalled_jobs

        async with async_session() as db:
            reaped = await reap_stalled_jobs(db)
            if reaped:
                logger.warning("Startup reaper recovered %d stalled job(s): %s", len(reaped), reaped)
    except Exception as e:
        logger.error("Startup job reaper sweep failed: %s", e)

    logger.info("Pinterest Realism Engine backend is READY.")
    yield

    logger.info("Shutting down scheduler...")
    stop_scheduler()


app = FastAPI(
    title="Pinterest Realism Engine",
    version="2.0.0",
    description="Automated UGC-style Pinterest Affiliate System with Photographic Realism",
    lifespan=lifespan,
)

# ── CORS Middleware ──────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Static Files (Storage, Data & Lookbooks) ────
settings.ensure_storage_dirs()
app.mount("/data", StaticFiles(directory=settings.storage_path), name="data")
app.mount("/storage", StaticFiles(directory=settings.storage_path), name="storage")

# ── Mount API Routers ────────────────────────────
app.include_router(references.router)
app.include_router(jobs.router)
app.include_router(generation.router)
app.include_router(pins.router)
app.include_router(products.router)
app.include_router(debug.router)
app.include_router(lookbooks.router)
app.include_router(amazon.router)
app.include_router(library.router)


# ── Health Check ─────────────────────────────────
@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "app_env": settings.app_env,
        "vault_connected": True,
        "providers": {
            "primary": "opencode.ai" if settings.opencode_api_key else "openrouter/gemini",
            "text": settings.opencode_text_model if settings.opencode_api_key else settings.openrouter_model,
            "vision": settings.opencode_vision_model if settings.opencode_api_key else settings.gemini_model,
        },
    }


# ── Vault Sync Endpoint ──────────────────────────
@app.post("/api/vault/sync")
async def trigger_vault_sync():
    """Trigger full sync of all live database entities to the Obsidian Vault."""
    try:
        from scripts.sync_all_to_vault import sync_all
        await sync_all()
        return {"status": "success", "message": "Obsidian Vault fully synced with live database."}
    except Exception as e:
        logger.error("Vault sync failed: %s", e)
        return {"status": "error", "message": str(e)}


# ── Global Exception Handler (Auto-Diagnostics & Vault Sync) ──
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception on %s %s: %s", request.method, request.url.path, exc)
    try:
        diag = record_diagnostic_error(
            exc,
            subsystem="API",
            context={"method": request.method, "url": str(request.url), "path": request.url.path},
        )
        return JSONResponse(
            status_code=500,
            content={
                "detail": f"[{diag.subsystem}] {diag.error_type}: {diag.message}",
                "diagnostic": diag.to_dict(),
                "suggested_fix": diag.suggested_fix,
            },
        )
    except Exception:
        return JSONResponse(
            status_code=500,
            content={"detail": "An internal error occurred and was logged."},
        )
