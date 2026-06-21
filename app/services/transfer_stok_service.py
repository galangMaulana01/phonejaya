from datetime import datetime, timezone
from typing import Optional, List
from motor.motor_asyncio import AsyncIOMotorDatabase
from fastapi import HTTPException

from app.schemas.transfer_stok import (
    TransferStokCreateRequest,
    TransferStokRespondRequest,
    TransferStokResponse,
    TransferUnitDetail,
    StatusTransferEnum,
)
from app.services.log_service import write_log
from app.utils.formatters import fmt_waktu
from app.utils.id_generator import next_unit_id


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt(doc: dict) -> TransferStokResponse:
    units = [
        TransferUnitDetail(
            unit_id_asal=u.get("unit_id_asal", ""),
            unit_id_baru=u.get("unit_id_baru"),
            merk=u.get("merk", ""),
            tipe=u.get("tipe", ""),
            storage=u.get("storage", "-"),
            imei=u.get("imei", "-"),
            kondisi=u.get("kondisi", ""),
            status_unit=u.get("status_unit", ""),
        )
        for u in doc.get("units", [])
    ]
    return TransferStokResponse(
        id=str(doc["_id"]),
        transfer_id=doc.get("transfer_id", str(doc["_id"])),
        cabang_asal=doc.get("cabang_asal", ""),
        cabang_tujuan=doc.get("cabang_tujuan", ""),
        units=units,
        jumlah=doc.get("jumlah", len(units)),
        status=doc.get("status", "Pending"),
        catatan=doc.get("catatan", ""),
        catatan_respon=doc.get("catatan_respon", ""),
        dibuat_oleh=doc.get("dibuat_oleh", ""),
        direspon_oleh=doc.get("direspon_oleh", ""),
        created_at=fmt_waktu(doc["created_at"]) if doc.get("created_at") else "",
        updated_at=fmt_waktu(doc["updated_at"]) if doc.get("updated_at") else None,
    )


async def _next_transfer_id(db: AsyncIOMotorDatabase) -> str:
    res = await db.counters.find_one_and_update(
        {"_id": "TRF"},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True,
    )
    return f"TRF-{str(res['seq']).zfill(3)}"


def _parse_kode(unit_id: str) -> tuple[str, str]:
    """
    Ekstrak kat_kode dan kondisi_kode dari unit_id.
    Format: {CABANG}-{KAT}-{KONDISI}-{SEQ}
    Contoh: JYP-IP-BN-001 → ('IP', 'BN')
    """
    parts = unit_id.split("-")
    if len(parts) < 4:
        raise ValueError(f"Format unit_id tidak valid: {unit_id}")
    # parts[0] = cabang, parts[1] = kat, parts[2] = kondisi, parts[-1] = seq
    kat_kode     = parts[1]
    kondisi_kode = parts[2]
    return kat_kode, kondisi_kode


# ── Service Functions ─────────────────────────────────────────────────────────

async def list_transfers(
    db: AsyncIOMotorDatabase,
    cabang: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
) -> List[TransferStokResponse]:
    query: dict = {}
    if status:
        query["status"] = status
    if cabang:
        # Tampilkan transfer yang melibatkan cabang ini (sebagai asal atau tujuan)
        query["$or"] = [{"cabang_asal": cabang}, {"cabang_tujuan": cabang}]
    docs = await db.transfer_stok.find(query).sort("created_at", -1).to_list(length=limit)
    return [_fmt(d) for d in docs]


async def create_transfer(
    db: AsyncIOMotorDatabase,
    payload: TransferStokCreateRequest,
    actor: str,
    cabang_asal: str,
) -> TransferStokResponse:
    # Tidak boleh transfer ke cabang sendiri
    if payload.cabang_tujuan == cabang_asal:
        raise HTTPException(
            status_code=400,
            detail="Tidak bisa transfer ke cabang sendiri"
        )

    # Validasi cabang tujuan exist dan aktif
    cab_tujuan = await db.cabang.find_one({"kode": payload.cabang_tujuan, "aktif": True})
    if not cab_tujuan:
        raise HTTPException(
            status_code=404,
            detail=f"Cabang tujuan '{payload.cabang_tujuan}' tidak ditemukan atau tidak aktif"
        )

    # Deduplikasi unit_ids dari request
    seen_ids = set()
    unit_ids_clean = []
    for item in payload.unit_ids:
        if item.unit_id not in seen_ids:
            seen_ids.add(item.unit_id)
            unit_ids_clean.append(item.unit_id)

    # Validasi setiap unit — ketat per unit
    errors: List[str] = []
    valid_units: List[dict] = []

    for uid in unit_ids_clean:
        unit = await db.units.find_one({"unit_id": uid})
        if not unit:
            errors.append(f"{uid}: tidak ditemukan")
            continue
        if unit.get("cabang") != cabang_asal:
            errors.append(f"{uid}: bukan milik cabang {cabang_asal}")
            continue
        if unit.get("status") != "Tersedia":
            errors.append(f"{uid}: status harus 'Tersedia' (saat ini '{unit.get('status')}')")
            continue
        valid_units.append(unit)

    if errors:
        raise HTTPException(
            status_code=422,
            detail={"message": "Validasi unit gagal", "errors": errors}
        )

    # Cek apakah ada unit yang sudah ada di transfer Pending lain
    pending_unit_ids = set()
    pending_transfers = await db.transfer_stok.find({"status": "Pending"}).to_list(length=None)
    for t in pending_transfers:
        for u in t.get("units", []):
            pending_unit_ids.add(u.get("unit_id_asal", ""))

    conflicts = [uid for uid in unit_ids_clean if uid in pending_unit_ids]
    if conflicts:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Unit sudah ada di transfer Pending lain",
                "conflicts": conflicts,
            }
        )

    # Build unit detail list untuk dokumen
    unit_docs = [
        {
            "unit_id_asal": u["unit_id"],
            "unit_id_baru": None,
            "merk":         u.get("merk", ""),
            "tipe":         u.get("tipe", ""),
            "storage":      u.get("storage", "-"),
            "imei":         u.get("imei", "-"),
            "kondisi":      u.get("kondisi", ""),
            "status_unit":  u.get("status", ""),
        }
        for u in valid_units
    ]

    transfer_id = await _next_transfer_id(db)
    now = datetime.now(timezone.utc)

    doc = {
        "transfer_id":   transfer_id,
        "cabang_asal":   cabang_asal,
        "cabang_tujuan": payload.cabang_tujuan,
        "units":         unit_docs,
        "jumlah":        len(unit_docs),
        "status":        "Pending",
        "catatan":       payload.catatan,
        "catatan_respon": "",
        "dibuat_oleh":   actor,
        "direspon_oleh": "",
        "created_at":    now,
        "updated_at":    None,
    }

    result = await db.transfer_stok.insert_one(doc)
    doc["_id"] = result.inserted_id

    await write_log(
        db, actor,
        "Buat Transfer Stok",
        f"{transfer_id} • {len(unit_docs)} unit dari {cabang_asal} → {payload.cabang_tujuan}",
        cabang_asal,
    )

    return _fmt(doc)


async def respond_transfer(
    db: AsyncIOMotorDatabase,
    transfer_id: str,
    payload: TransferStokRespondRequest,
    actor: str,
    user_role: str,
    user_cabang: Optional[str],
) -> TransferStokResponse:
    doc = await db.transfer_stok.find_one({"transfer_id": transfer_id})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Transfer {transfer_id} tidak ditemukan")

    if doc["status"] != "Pending":
        raise HTTPException(
            status_code=400,
            detail=f"Transfer sudah direspon sebelumnya (status: {doc['status']})"
        )

    # Kepala cabang hanya bisa respon transfer yang ditujukan ke cabangnya
    if user_role == "kepala_cabang" and user_cabang != doc["cabang_tujuan"]:
        raise HTTPException(
            status_code=403,
            detail="Kamu hanya bisa merespon transfer yang ditujukan ke cabangmu"
        )

    now = datetime.now(timezone.utc)

    if payload.status == StatusTransferEnum.diterima:
        await _proses_terima(db, doc, actor, now)
    else:
        await _proses_tolak(db, doc, actor, payload.catatan, now)

    update = {
        "status":        payload.status.value,
        "catatan_respon": payload.catatan,
        "direspon_oleh": actor,
        "updated_at":    now,
    }
    await db.transfer_stok.update_one({"transfer_id": transfer_id}, {"$set": update})

    updated = await db.transfer_stok.find_one({"transfer_id": transfer_id})
    return _fmt(updated)


async def _proses_terima(
    db: AsyncIOMotorDatabase,
    doc: dict,
    actor: str,
    now: datetime,
) -> None:
    """
    Untuk setiap unit:
    1. Generate unit_id baru dengan format cabang tujuan
    2. Update unit: unit_id baru, cabang baru
    3. Update embedded unit_id_baru di dokumen transfer
    4. Write log untuk cabang asal DAN cabang tujuan
    """
    cabang_tujuan = doc["cabang_tujuan"]
    cabang_asal   = doc["cabang_asal"]
    transfer_id   = doc["transfer_id"]
    unit_updates  = []

    for unit_item in doc.get("units", []):
        unit_id_asal = unit_item["unit_id_asal"]

        # Fetch unit terkini — pastikan masih Tersedia dan cabang masih sama
        unit = await db.units.find_one({"unit_id": unit_id_asal})
        if not unit:
            raise HTTPException(
                status_code=404,
                detail=f"Unit {unit_id_asal} tidak ditemukan saat proses terima"
            )
        if unit.get("status") != "Tersedia":
            raise HTTPException(
                status_code=409,
                detail=f"Unit {unit_id_asal} tidak lagi berstatus 'Tersedia' (sudah {unit.get('status')}). Transfer dibatalkan."
            )
        if unit.get("cabang") != cabang_asal:
            raise HTTPException(
                status_code=409,
                detail=f"Unit {unit_id_asal} tidak lagi berada di cabang {cabang_asal}."
            )

        # Generate unit_id baru dengan cabang tujuan
        try:
            kat_kode, kondisi_kode = _parse_kode(unit_id_asal)
        except ValueError as e:
            raise HTTPException(status_code=500, detail=str(e))

        unit_id_baru = await next_unit_id(db, kat_kode, kondisi_kode, cabang_tujuan)

        # Update unit document
        await db.units.update_one(
            {"unit_id": unit_id_asal},
            {"$set": {
                "unit_id":    unit_id_baru,
                "cabang":     cabang_tujuan,
                "updated_at": now,
            }}
        )

        unit_updates.append({
            "unit_id_asal": unit_id_asal,
            "unit_id_baru": unit_id_baru,
        })

        # Log per unit
        await write_log(
            db, actor,
            "Transfer Stok Diterima",
            f"{transfer_id} • {unit_id_asal} → {unit_id_baru} | {cabang_asal} → {cabang_tujuan}",
            cabang_tujuan,  # log di cabang tujuan (penerima)
        )

    # Update embedded unit_id_baru di dokumen transfer
    updated_units = list(doc.get("units", []))
    id_map = {u["unit_id_asal"]: u["unit_id_baru"] for u in unit_updates}
    for u in updated_units:
        u["unit_id_baru"] = id_map.get(u["unit_id_asal"])

    await db.transfer_stok.update_one(
        {"transfer_id": transfer_id},
        {"$set": {"units": updated_units}}
    )

    # Log ringkasan di cabang asal juga
    await write_log(
        db, actor,
        "Transfer Stok Diterima",
        f"{transfer_id} • {len(unit_updates)} unit keluar dari {cabang_asal} → {cabang_tujuan}",
        cabang_asal,
    )


async def _proses_tolak(
    db: AsyncIOMotorDatabase,
    doc: dict,
    actor: str,
    catatan: str,
    now: datetime,
) -> None:
    """Tolak — unit tidak dipindah, cukup log."""
    transfer_id   = doc["transfer_id"]
    cabang_asal   = doc["cabang_asal"]
    cabang_tujuan = doc["cabang_tujuan"]
    jumlah        = doc.get("jumlah", len(doc.get("units", [])))

    await write_log(
        db, actor,
        "Transfer Stok Ditolak",
        f"{transfer_id} • {jumlah} unit dari {cabang_asal} ditolak oleh {cabang_tujuan}"
        + (f" | Alasan: {catatan}" if catatan else ""),
        cabang_tujuan,
    )
    await write_log(
        db, actor,
        "Transfer Stok Ditolak",
        f"{transfer_id} • {jumlah} unit ditolak oleh {cabang_tujuan}"
        + (f" | Alasan: {catatan}" if catatan else ""),
        cabang_asal,
    )


async def count_pending_for_cabang(
    db: AsyncIOMotorDatabase,
    cabang: str,
) -> int:
    """Dipakai endpoint notifikasi polling — hitung transfer Pending ke cabang ini."""
    return await db.transfer_stok.count_documents({
        "cabang_tujuan": cabang,
        "status": "Pending",
    })


async def list_pending_for_cabang(
    db: AsyncIOMotorDatabase,
    cabang: str,
    limit: int = 20,
) -> List[TransferStokResponse]:
    """List transfer Pending yang ditujukan ke cabang ini — untuk notif polling."""
    docs = await db.transfer_stok.find({
        "cabang_tujuan": cabang,
        "status": "Pending",
    }).sort("created_at", -1).to_list(length=limit)
    return [_fmt(d) for d in docs]
