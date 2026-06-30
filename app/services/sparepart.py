from datetime import datetime, timezone
from typing import Optional, List
from motor.motor_asyncio import AsyncIOMotorDatabase
from fastapi import HTTPException

from app.schemas.sparepart import (
    SparepartCreateRequest, SparepartUpdateStokRequest, SparepartResponse
)
from app.services.log_service import write_log


def _fmt(doc: dict) -> SparepartResponse:
    p = doc.get("dimensi_p")
    l = doc.get("dimensi_l")
    t = doc.get("dimensi_t")
    dim_str = f"{p} x {l} x {t} cm" if p and l and t else ""
    return SparepartResponse(
        id          = str(doc["_id"]),
        sp_id       = doc.get("sp_id", str(doc["_id"])),
        nama        = doc.get("nama", ""),
        kategori    = doc.get("kategori", "Umum"),
        satuan      = doc.get("satuan", "pcs"),
        stok        = doc.get("stok", 0),
        harga_beli  = doc.get("harga_beli", 0),
        harga_jual  = doc.get("harga_jual", 0),
        dimensi_p   = p,
        dimensi_l   = l,
        dimensi_t   = t,
        catatan     = doc.get("catatan", ""),
        cabang      = doc.get("cabang", ""),
        dimensi_str = dim_str,
    )


async def _next_sp_id(db: AsyncIOMotorDatabase) -> str:
    result = await db.counters.find_one_and_update(
        {"_id": "SP"},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True,
    )
    return f"SP-{str(result['seq']).zfill(3)}"


async def list_sparepart(
    db: AsyncIOMotorDatabase,
    cabang: Optional[str] = None,
    kategori: Optional[str] = None,
) -> List[SparepartResponse]:
    query: dict = {}
    if cabang:   query["cabang"]   = cabang
    if kategori: query["kategori"] = kategori
    docs = await db.sparepart.find(query).sort("nama", 1).to_list(length=None)
    return [_fmt(d) for d in docs]


async def create_sparepart(
    db: AsyncIOMotorDatabase,
    payload: SparepartCreateRequest,
    actor: str,
) -> SparepartResponse:
    sp_id = await _next_sp_id(db)
    now   = datetime.now(timezone.utc)
    doc   = {
        "sp_id":      sp_id,
        "nama":       payload.nama,
        "kategori":   payload.kategori,
        "satuan":     payload.satuan,
        "stok":       payload.stok,
        "harga_beli": payload.harga_beli,
        "harga_jual": payload.harga_jual,
        "dimensi_p":  payload.dimensi_p,
        "dimensi_l":  payload.dimensi_l,
        "dimensi_t":  payload.dimensi_t,
        "catatan":    payload.catatan,
        "cabang":     payload.cabang,
        "created_at": now,
        "created_by": actor,
        "updated_at": None,
    }
    result = await db.sparepart.insert_one(doc)
    doc["_id"] = result.inserted_id
    await write_log(db, actor, "Tambah Sparepart", f"{sp_id} • {payload.nama} stok:{payload.stok}", payload.cabang)
    return _fmt(doc)


async def update_stok(
    db: AsyncIOMotorDatabase,
    sp_id: str,
    payload: SparepartUpdateStokRequest,
    actor: str,
    user_role: str = '',
    user_cabang: str = '',
) -> SparepartResponse:
    sp = await db.sparepart.find_one({"sp_id": sp_id})
    if not sp:
        raise HTTPException(status_code=404, detail=f"Sparepart {sp_id} tidak ditemukan")
    if user_role == 'kepala_cabang' and sp.get('cabang') != user_cabang:
        raise HTTPException(status_code=403, detail='Sparepart bukan milik cabangmu')

    stok_baru = sp["stok"] + payload.delta
    if stok_baru < 0:
        raise HTTPException(status_code=400, detail=f"Stok tidak cukup. Stok saat ini: {sp['stok']}")

    now = datetime.now(timezone.utc)
    await db.sparepart.update_one(
        {"sp_id": sp_id},
        {"$set": {"stok": stok_baru, "updated_at": now}}
    )
    updated = await db.sparepart.find_one({"sp_id": sp_id})
    aksi = "tambah" if payload.delta > 0 else "kurangi"
    await write_log(db, actor, "Update Stok Sparepart",
        f"{sp_id} • {sp['nama']} {aksi} {abs(payload.delta)} → stok:{stok_baru}", sp.get("cabang",""))
    return _fmt(updated)


async def kurangi_stok_batch(
    db: AsyncIOMotorDatabase,
    items: list,   # [{"sp_id": str, "jumlah": int}]
    actor: str,
    cabang: str,
) -> None:
    """Kurangi stok beberapa sparepart sekaligus — dipanggil saat service Selesai."""
    for item in items:
        sp = await db.sparepart.find_one({"sp_id": item["sp_id"]})
        if not sp:
            continue  # skip kalau sparepart sudah dihapus
        # Hitung aktual yang bisa dikurangi (tidak boleh minus)
        actual_deducted = min(sp["stok"], item["jumlah"])
        stok_baru = sp["stok"] - actual_deducted
        await db.sparepart.update_one(
            {"sp_id": item["sp_id"]},
            {"$set": {"stok": stok_baru, "updated_at": datetime.now(timezone.utc)}}
        )
        await write_log(db, actor, "Pemakaian Sparepart Service",
            f"{item['sp_id']} • {sp['nama']} -{actual_deducted} (diminta {item['jumlah']}) → stok:{stok_baru}", cabang)
