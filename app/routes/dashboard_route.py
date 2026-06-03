from fastapi import APIRouter, Depends, Query
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.config.database import get_db
from app.schemas.common import ok
from app.services import dashboard_service
from app.middlewares.auth import require_owner

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/stats")
async def dashboard_stats(
    cabang: Optional[str] = Query(None),
    db:     AsyncIOMotorDatabase = Depends(get_db),
    _user:  dict = Depends(require_owner),
):
    stats = await dashboard_service.get_stats(db, cabang=cabang)
    return ok(stats)


@router.get("/trend")
async def dashboard_trend(
    cabang: Optional[str] = Query(None),
    hari:   int            = Query(30, ge=7, le=90),
    db:     AsyncIOMotorDatabase = Depends(get_db),
    _user:  dict = Depends(require_owner),
):
    """Trend penjualan & profit per hari. Default 30 hari terakhir."""
    data = await dashboard_service.get_trend(db, cabang=cabang, hari=hari)
    return ok(data)
