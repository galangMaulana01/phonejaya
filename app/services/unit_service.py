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
    return UnitResponse(
        id=str(doc["_id"]),
        unit_id=doc["unit_id"],
        merk=doc["merk"],
        tipe=doc["tipe"],
        storage=doc["storage"],
        ram=doc.get("ram", "-"),
        warna=doc["warna"],
        imei=doc["imei"],
        harga_modal=doc["harga_modal"],
        harga_jual=doc.get("harga_jual", 0),
        kondisi=doc["kondisi"],
        kondisi_hp=doc.get("kondisi_hp", "Mulus"),
        battery=doc["battery"],
        status=doc["status"],
        kategori=doc["kategori"],
        catatan=doc.get("catatan", ""),
        cabang=doc["cabang"],
        locked=doc.get("locked", True),
        service_id=doc.get("service_id"),
    )


async def list_units(
    db,
    cabang: Optional[str] = None,
    status_filter: Optional[str] = None,
) -> List[UnitResponse]:
    query: dict = {}
    if cabang:
        query["cabang"] = cabang
    if status_filter and status_filter != "Semua":
        query["status"] = status_filter
    docs = await db.units.find(query).sort("_id", -1).to_list(length=None)
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
        existing = await db.units.find_one({"imei": payload.imei, "status": {"$ne": "Sold"}})
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
        "unit_id":     unit_id,
        "merk":        payload.merk,
        "tipe":        payload.tipe,
        "storage":     payload.storage,
        "ram":          payload.ram,
        "warna":       payload.warna,
        "imei":        payload.imei,
        "harga_modal": payload.harga_modal,
        "harga_jual":  0 if is_repair else payload.harga_jual,
        "kondisi":     resolve_kondisi(payload.kondisi_kode),
        "kondisi_hp":  payload.kondisi_hp.value,
        "battery":     payload.battery,
        "status":      status,
        "kategori":    resolve_kategori(payload.kat_kode),
        "catatan":     payload.catatan,
        "cabang":      payload.cabang,
        "locked":      True,       # SELALU locked setelah posting
        "created_at":  now,
        "created_by":  actor,
        "service_id":  None,
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
            "cabang":           payload.cabang,
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
