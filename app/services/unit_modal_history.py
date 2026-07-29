from datetime import datetime, timezone, timedelta
from typing import Optional, List
from motor.motor_asyncio import AsyncIOMotorDatabase
from fastapi import HTTPException
from bson import ObjectId

from app.schemas.unit_modal_history import UnitModalHistoryCreateRequest, UnitModalHistoryResponse
from app.utils.formatters import fmt_waktu


def _fmt(doc: dict) -> UnitModalHistoryResponse:
    return UnitModalHistoryResponse(
        id=str(doc["_id"]),
        unit_id=doc.get("unit_id", ""),
        sebelum=doc.get("sebelum", 0),
        sesudah=doc.get("sesudah", 0),
        delta=doc.get("delta", 0),
        ref_type=doc.get("ref_type", ""),
        ref_id=doc.get("ref_id", ""),
        actor_id=doc.get("actor_id", ""),
        actor_name=doc.get("actor_name", ""),
        actor_role=doc.get("actor_role", ""),
        catatan=doc.get("catatan", ""),
        timestamp=fmt_waktu(doc["timestamp"]) if doc.get("timestamp") else "",
    )


async def create_modal_history(db: AsyncIOMotorDatabase, payload: UnitModalHistoryCreateRequest) -> UnitModalHistoryResponse:
    """Create modal history entry (internal use only)"""
    now = datetime.now(timezone.utc)
    doc = {
        "unit_id": payload.unit_id,
        "sebelum": payload.sebelum,
        "sesudah": payload.sesudah,
        "delta": payload.delta,
        "ref_type": payload.ref_type.value,
        "ref_id": payload.ref_id,
        "actor_id": payload.actor_id,
        "actor_name": payload.actor_name,
        "actor_role": payload.actor_role,
        "catatan": payload.catatan,
        "timestamp": now,
    }
    result = await db.unit_modal_history.insert_one(doc)
    doc["_id"] = result.inserted_id
    return _fmt(doc)


async def list_modal_history(
    db: AsyncIOMotorDatabase,
    unit_id: str,
    limit: int = 50,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> List[UnitModalHistoryResponse]:
    """List modal history for a unit"""
    query = {"unit_id": unit_id}
    if date_from or date_to:
        wf = {}
        if date_from:
            wf["$gte"] = datetime.fromisoformat(date_from.replace("Z", "")).replace(tzinfo=timezone.utc)
        if date_to:
            dt = datetime.fromisoformat(date_to.replace("Z", "")).replace(tzinfo=timezone.utc) + timedelta(days=1)
            wf["$lt"] = dt
        query["timestamp"] = wf
    docs = await db.unit_modal_history.find(query).sort("timestamp", -1).limit(limit).to_list(length=limit)
    return [_fmt(d) for d in docs]


async def get_modal_history_by_id(db: AsyncIOMotorDatabase, history_id: str) -> UnitModalHistoryResponse:
    """Get modal history by _id"""
    doc = await db.unit_modal_history.find_one({"_id": ObjectId(history_id)})
    if not doc:
        raise HTTPException(404, f"Modal history {history_id} tidak ditemukan")
    return _fmt(doc)