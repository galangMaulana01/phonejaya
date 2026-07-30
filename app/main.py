import logging
import logging.config
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.config.settings import settings
from app.routes import (
    auth, units, transaksi, karyawan, log, dashboard,
    service, customer, sparepart, cabang, request_sparepart,
    transfer_stok, influencer, upload, cod, unit_modal_history,
)
from app.config.database import init_db, get_db, get_client
import logging

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO if settings.is_production else logging.DEBUG,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)


async def warmup_db():
    """Warm up MongoDB connection on startup to avoid cold start latency."""
    try:
        # Initialize indexes
        await init_db()
        # Test connection with a simple ping
        client = get_client()
        await client.admin.command("ping")
        # Verify customers collection exists
        db = client[settings.MONGO_DB]
        collections = await db.list_collection_names()
        logger.info("Database connection warmup successful. Collections: %s", collections)
        return True
    except Exception as e:
        logger.warning("Database warmup failed: %s", e)
        return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Application starting up...")
    await warmup_db()
    logger.info("Application startup complete")
    yield
    # Shutdown
    logger.info("Application shutting down...")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        description="JAYAPHONE Backend API — Vercel Serverless",
        version="2.0.0",
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        lifespan=lifespan,
    )

    # Rate limiter
    limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore

    # CORS — allow specific origins untuk keamanan
    # Vercel frontend domains
    allowed_origins = [
        "https://jayaphone.vercel.app",
        "https://phonejaya.vercel.app",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ]

    # Allow additional origins from env (comma-separated)
    if settings.CORS_ORIGINS and settings.CORS_ORIGINS != "*":
        allowed_origins.extend([o.strip() for o in settings.CORS_ORIGINS.split(",")])

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # HTTPException handler
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"success": False, "message": exc.detail, "data": None},
        )

    # Global error handler
    @app.exception_handler(Exception)
    async def unhandled_exception(request: Request, exc: Exception):
        # Don't handle HTTPException here - let FastAPI's default handler deal with it
        if isinstance(exc, HTTPException):
            raise exc
        logger.exception("Unhandled error: %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "Internal server error", "data": None},
        )

    # Routes
    PREFIX = "/api/v1"
    app.include_router(auth.router, prefix=PREFIX)
    app.include_router(units.router, prefix=PREFIX)
    app.include_router(transaksi.router, prefix=PREFIX)
    app.include_router(karyawan.router, prefix=PREFIX)
    app.include_router(log.router, prefix=PREFIX)
    app.include_router(dashboard.router, prefix=PREFIX)
    app.include_router(service.router, prefix=PREFIX)
    app.include_router(customer.router, prefix=PREFIX)
    app.include_router(sparepart.router, prefix=PREFIX)
    app.include_router(cabang.router, prefix=PREFIX)
    app.include_router(request_sparepart.router, prefix=PREFIX)
    app.include_router(transfer_stok.router, prefix=PREFIX)
    app.include_router(influencer.router, prefix=PREFIX)
    app.include_router(upload.router, prefix=PREFIX)
    app.include_router(cod.router, prefix=PREFIX)
    app.include_router(unit_modal_history.router, prefix=PREFIX)

    @app.on_event("startup")
    async def startup_event():
        await init_db()

    @app.get("/health", tags=["Health"])
    async def health():
        return {"status": "ok", "app": settings.APP_NAME, "version": "2.0.0"}

    return app


app = create_app()

# Export limiter for route usage
limiter = app.state.limiter