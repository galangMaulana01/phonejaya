from datetime import datetime, timezone
from typing import Optional, List
from motor.motor_asyncio import AsyncIOMotorDatabase
from fastapi import HTTPException

from app.schemas.unit import (
    UnitCreateRequest, ApproveRepairRequest,
    UnitResponse, KondisiHP
)
from app.utils.id_generator import next_unit_id, next_service_id, resolve_kategori, resolve_kondisi
from app.utils.formatters import fmt_waktu
from app.services.log_service import write_log


def _fmt(doc: dict) -> UnitResponse:
    from app.utils.formatters import fmt_waktu
    return UnitResponse(
        id=str(doc["_id"]),
        unit_id=doc["unit_id"],
        merk=doc["merk"],
        tipe=doc["tipe"],
        storage=doc["storage"],
        ram=doc.get("ram", "-"),
        warna=doc["warna"],
        imei=doc["imei"],
        imei2=doc.get("imei2", "-"),
        tipe_sim=doc.get("tipe_sim", "Single SIM"),
        keamanan=doc.get("keamanan", "Tidak Ada"),
        speaker=doc.get("speaker", "Normal"),
        lcd=doc.get("lcd", "Original"),
        harga_modal=doc["harga_modal"],
        harga_jual=doc.get("harga_jual", 0),
        kondisi=doc["kondisi"],
        kondisi_hp=doc.get("kondisi_hp", "Mulus"),
        battery=doc["battery"],
        battery_health=doc.get("battery_health", 0),
        status=doc["status"],
        kategori=doc["kategori"],
        catatan=doc.get("catatan", ""),
        cabang=doc["cabang"],
        locked=doc.get("locked", True),
        garansi_toko=doc.get("garansi_toko", 7),
        input_oleh=doc.get("created_by", ""),
        tgl_masuk=fmt_waktu(doc["created_at"]) if doc.get("created_at") else "",
        tgl_terjual=fmt_waktu(doc["tgl_terjual"]) if doc.get("tgl_terjual") else None,
        service_id=doc.get("service_id"),
        foto_url=doc.get("foto_url"),
    )


async def list_units(
    db,
    cabang: Optional[str] = None,
    status_filter: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 200,
) -> List[UnitResponse]:
    query: dict = {}
    if cabang:
        query["cabang"] = cabang
    if status_filter and status_filter != "Semua":
        query["status"] = status_filter
    if q:
        regex = {"$regex": q, "$options": "i"}
        query["$or"] = [
            {"merk": regex},
            {"tipe": regex},
            {"imei": regex},
            {"unit_id": regex},
        ]
    docs = await db.units.find(query).sort("_id", -1).to_list(length=limit)
    return [_fmt(d) for d in docs]


async def create_unit(
    db,
    payload: UnitCreateRequest,
    actor: str,
) -> UnitResponse:
    """
    Input HP baru dari penjual.
    - kondisi_hp = Mulus  → status Tersedia, locked=True
    - kondisi_hp = Repair → status Service, locked=True, auto-create tiket service
    Unit LANGSUNG di-lock setelah diposting. Tidak bisa diedit siapapun.
    """
    # Cek IMEI duplikat
    if payload.imei and payload.imei != "-":
        # Cek IMEI duplikat kecuali unit yang sudah Sold atau Ditolak
        existing = await db.units.find_one({
            "imei": payload.imei,
            "status": {"$nin": ["Sold", "Ditolak"]}
        })
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"IMEI {payload.imei} sudah terdaftar di sistem"
            )

    # Validasi: kalau Repair wajib ada keluhan
    if payload.kondisi_hp == KondisiHP.repair and not payload.keluhan.strip():
        raise HTTPException(
            status_code=422,
            detail="Keluhan wajib diisi untuk HP yang butuh repair"
        )

    # Kalau Mulus wajib ada harga jual
    if payload.kondisi_hp == KondisiHP.mulus and payload.harga_jual <= 0:
        raise HTTPException(
            status_code=422,
            detail="Harga jual wajib diisi untuk HP kondisi Mulus"
        )

    unit_id = await next_unit_id(db, payload.kat_kode, payload.kondisi_kode, payload.cabang)
    now = datetime.now(timezone.utc)

    # Status berdasarkan kondisi HP
    is_repair = payload.kondisi_hp == KondisiHP.repair
    status    = "Service" if is_repair else "Tersedia"

    doc = {
        "unit_id":       unit_id,
        "merk":          payload.merk,
        "tipe":          payload.tipe,
        "storage":       payload.storage,
        "ram":           payload.ram,
        "warna":         payload.warna,
        "imei":          payload.imei,
        "imei2":         payload.imei2,
        "tipe_sim":      payload.tipe_sim,
        "keamanan":      payload.keamanan,
        "speaker":       payload.speaker,
        "lcd":           payload.lcd,
        "harga_modal":   payload.harga_modal,
        "harga_jual":    0 if is_repair else payload.harga_jual,
        "kondisi":       resolve_kondisi(payload.kondisi_kode),
        "kondisi_hp":    payload.kondisi_hp.value,
        "battery":       payload.battery,
        "battery_health": payload.battery_health,
        "status":        status,
        "kategori":      resolve_kategori(payload.kat_kode),
        "catatan":       payload.catatan,
        "cabang":        payload.cabang,
        "locked":        True,
        "garansi_toko":  payload.garansi_toko,
        "created_at":    now,
        "created_by":    actor,
        "tgl_terjual":   None,
        "service_id":    None,
        "foto_url":      payload.foto_url,
    }

    result = await db.units.insert_one(doc)
    doc["_id"] = result.inserted_id

    await write_log(
        db, actor, "Input Unit Masuk",
        f"{unit_id} • {payload.merk} {payload.tipe} [{payload.kondisi_hp.value}]",
        payload.cabang
    )

    # Kalau Repair → auto-create tiket service
    if is_repair:
        service_id = await next_service_id(db)
        service_doc = {
            "service_id":       service_id,
            "unit_id":          unit_id,
            "unit_label":       (f"{payload.merk} {payload.tipe} {payload.storage}" + (f" {payload.ram}" if payload.ram and payload.ram != "-" else "")),
            "nama_customer":    "",
            "kontak_customer":  "",
            "keluhan":          payload.keluhan,
            "catatan_kerusakan": "",
            "status":           "Antrian",
            "teknisi":          "",
            "foto_urls":        [],
            "foto_before_urls": [],
            "foto_after_urls":  [],
            "cabang":           payload.cabang,
            "sparepart_items":  [{"sp_id": s.sp_id, "jumlah": s.jumlah} for s in payload.sparepart_items] if payload.sparepart_items else [],
            "created_at":       now,
            "updated_at":       None,
            "created_by":       actor,
        }
        await db.service.insert_one(service_doc)

        # Simpan service_id di unit
        await db.units.update_one(
            {"unit_id": unit_id},
            {"$set": {"service_id": service_id}}
        )
        doc["service_id"] = service_id

        await write_log(
            db, actor, "Auto Buat Tiket Service",
            f"{service_id} → {unit_id} • {payload.merk} {payload.tipe}",
            payload.cabang
        )

    return _fmt(doc)


async def approve_repair(
    db,
    unit_id: str,
    payload: ApproveRepairRequest,
    actor: str,
) -> UnitResponse:
    """
    Kasir / Owner approve unit setelah teknisi selesai repair.
    Set harga jual → unit pindah ke stok Tersedia.
    Hanya bisa dilakukan kalau service sudah Selesai.
    """
    unit = await db.units.find_one({"unit_id": unit_id})
    if not unit:
        raise HTTPException(status_code=404, detail=f"Unit {unit_id} tidak ditemukan")

    if unit.get("kondisi_hp") != "Repair":
        raise HTTPException(
            status_code=400,
            detail="Unit ini bukan unit repair. Tidak perlu approval."
        )

    if unit.get("status") != "Service":
        raise HTTPException(
            status_code=400,
            detail=f"Unit tidak dalam status Service (status saat ini: {unit['status']})"
        )

    # Cek tiket service sudah Selesai
    service_id = unit.get("service_id")
    if service_id:
        svc = await db.service.find_one({"service_id": service_id})
        if svc and svc.get("status") not in ("Selesai", "Approved"):
            raise HTTPException(
                status_code=400,
                detail=f"Tiket service belum selesai (status: {svc.get('status')}). Teknisi harus update dulu ke Selesai."
            )

    now = datetime.now(timezone.utc)

    # Update unit → Tersedia + set harga jual
    await db.units.update_one(
        {"unit_id": unit_id},
        {"$set": {
            "harga_jual":   payload.harga_jual,
            "status":       "Tersedia",
            "approved_by":  actor,
            "approved_at":  now,
            "updated_at":   now,
        }}
    )

    # Update service → Approved
    if service_id:
        await db.service.update_one(
            {"service_id": service_id},
            {"$set": {"status": "Approved", "updated_at": now}}
        )

    updated = await db.units.find_one({"unit_id": unit_id})

    await write_log(
        db, actor, "Approve Repair",
        f"{unit_id} • {unit['merk']} {unit['tipe']} → Tersedia @ Rp {payload.harga_jual:,}",
        unit.get("cabang", "")
    )

    return _fmt(updated)
