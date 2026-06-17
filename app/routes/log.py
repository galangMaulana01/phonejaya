from fastapi import APIRouter, Depends, Query
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.config.database import get_db
from app.schemas.common import ok
from app.utils.formatters import fmt_waktu
from app.middlewares.auth import require_kepala_or_owner

router = APIRouter(prefix="/log", tags=["Log"])


@router.get("")
async def list_log(
    cabang: Optional[str] = Query(None),
    limit:     int = Query(100, ge=1, le=500),
    date_from: Optional[str] = Query(None),
    date_to:   Optional[str] = Query(None),
    db:     AsyncIOMotorDatabase = Depends(get_db),
    user:   dict = Depends(require_kepala_or_owner),
):
    query = {}
    # Owner bisa filter bebas, kepala_cabang paksa cabangnya
    if user.get("role") == "owner":
        if cabang: query["cabang"] = cabang
    else:
        query["cabang"] = user.get("cabang")

    if date_from or date_to:
        from datetime import datetime, timezone
        wf: dict = {}
        if date_from: wf["$gte"] = datetime.fromisoformat(date_from.replace("Z","")).replace(tzinfo=timezone.utc)
        if date_to:   wf["$lte"] = datetime.fromisoformat(date_to.replace("Z","")).replace(tzinfo=timezone.utc)
        query["waktu"] = wf
    cursor = db.log.find(query).sort("waktu", -1).limit(limit)
    docs   = await cursor.to_list(length=limit)
    data = [{
        "id":     str(d["_id"]),
        "waktu":  fmt_waktu(d["waktu"]),
        "user":   d["user"],
        "aksi":   d["aksi"],
        "detail": d["detail"],
        "cabang": d.get("cabang", ""),
    } for d in docs]
    return ok(data)
