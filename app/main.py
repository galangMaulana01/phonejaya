import logging
import logging.config
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config.settings import settings
from app.routes import (
    auth, units, transaksi, karyawan, log, dashboard,
    service, customer, sparepart, cabang, request_sparepart,
    transfer_stok,                                           # ← NEW
)

logging.basicConfig(
    level=logging.INFO if settings.is_production else logging.DEBUG,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        description="JAYAPONA Backend API — Vercel Serverless",
        version="2.0.0",
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
    )

    # CORS — allow all untuk kompatibilitas Vercel
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Global error handler
    @app.exception_handler(Exception)
    async def unhandled_exception(request: Request, exc: Exception):
        logger.exception("Unhandled error: %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "Internal server error", "data": None},
        )

    # Routes
    PREFIX = "/api/v1"
    app.include_router(auth.router,              prefix=PREFIX)
    app.include_router(units.router,             prefix=PREFIX)
    app.include_router(transaksi.router,         prefix=PREFIX)
    app.include_router(karyawan.router,          prefix=PREFIX)
    app.include_router(log.router,               prefix=PREFIX)
    app.include_router(dashboard.router,         prefix=PREFIX)
    app.include_router(service.router,           prefix=PREFIX)
    app.include_router(customer.router,          prefix=PREFIX)
    app.include_router(sparepart.router,         prefix=PREFIX)
    app.include_router(cabang.router,            prefix=PREFIX)
    app.include_router(request_sparepart.router, prefix=PREFIX)
    app.include_router(transfer_stok.router,     prefix=PREFIX)  # ← NEW

    @app.get("/health", tags=["Health"])
    async def health():
        return {"status": "ok", "app": settings.APP_NAME, "version": "2.0.0"}

    return app


app = create_app()
