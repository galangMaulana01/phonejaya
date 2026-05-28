from motor.motor_asyncio import AsyncIOMotorDatabase

_KATEGORI_MAP = {"IP":"iPhone","AI":"Android","TB":"Tablet","AC":"Accessories","SP":"Sparepart"}
_KONDISI_MAP  = {"BN":"Normal","MN":"Minus","EX":"Ex Inter","RJ":"Reject"}


async def _next_seq(db: AsyncIOMotorDatabase, key: str) -> int:
    result = await db.counters.find_one_and_update(
        {"_id": key},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True,
    )
    return result["seq"]


async def next_unit_id(db, kat: str, kondisi: str, cabang: str = "JYP") -> str:
    seq = await _next_seq(db, kat)
    return f"{cabang}-{kat}-{kondisi}-{str(seq).zfill(3)}"


async def next_trx_id(db) -> str:
    seq = await _next_seq(db, "TRX")
    return f"TRX-{str(seq).zfill(3)}"


async def next_service_id(db) -> str:
    seq = await _next_seq(db, "SVC")
    return f"SVC-{str(seq).zfill(3)}"


def resolve_kategori(kat_kode: str) -> str:
    return _KATEGORI_MAP.get(kat_kode, kat_kode)


def resolve_kondisi(kondisi_kode: str) -> str:
    return _KONDISI_MAP.get(kondisi_kode, kondisi_kode)
