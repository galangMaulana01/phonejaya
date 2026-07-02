from datetime import datetime, timezone
from typing import Optional, List
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.schemas.customer import CustomerCreateRequest, CustomerResponse
from app.utils.formatters import fmt_waktu
from app.services.log_service import write_log


def _fmt(doc: dict) -> CustomerResponse:
    return CustomerResponse(
        id=str(doc["_id"]), nama=doc["nama"],
        kontak=doc["kontak"], cabang=doc.get("cabang", ""),
        created_at=fmt_waktu(doc["created_at"]),
        points=doc.get("points", 0),
    )


async def list_customer(db, q: Optional[str]=None) -> List[CustomerResponse]:
    query: dict = {}
    if q: query["$or"] = [{"nama":{"$regex":q,"$options":"i"}},{"kontak":{"$regex":q,"$options":"i"}}]
    docs = await db.customers.find(query).sort("nama", 1).to_list(length=None)
    return [_fmt(d) for d in docs]


async def create_customer(db, payload: CustomerCreateRequest, actor: str) -> CustomerResponse:
    doc = {
        "nama": payload.nama, "kontak": payload.kontak,
        "created_at": datetime.now(timezone.utc),
        "points": 0,
    }
    result = await db.customers.insert_one(doc)
    doc["_id"] = result.inserted_id
    await write_log(db, actor, "Tambah Customer", payload.nama, payload.cabang)
    return _fmt(doc)
