from typing import Optional, List
from motor.motor_asyncio import AsyncIOMotorDatabase
from fastapi import HTTPException
from datetime import datetime, timezone
from bson import ObjectId
from app.schemas.transaksi import (
    TransaksiCreateRequest, TransaksiSparepartRequest, TransaksiResponse
)
from app.utils.id_generator import next_trx_id
from app.utils.formatters import fmt_waktu
from app.services.log_service import write_log
from app.services.customer_service import create_customer
from app.schemas.sparepart import DEFAULT_SPAREPART_JENIS


def _fmt(doc: dict) -> TransaksiResponse:
    return TransaksiResponse(
        id          = str(doc["_id"]),
        trx_id      = doc["trx_id"],
        tipe        = doc.get("tipe", "unit"),
        unit_id     = doc.get("unit_id"),
        unit_label  = doc.get("unit_label", ""),
        kasir       = doc["kasir"],
        harga_jual  = doc["harga_jual"],
        harga_modal = doc["harga_modal"],
        profit      = doc["profit"],
        waktu       = fmt_waktu(doc.get("waktu", datetime.now(timezone.utc))),
        catatan       = doc.get("catatan", ""),
        garansi_hari  = doc.get("garansi_hari", 7),
        biaya_garansi = doc.get("biaya_garansi", 0),
        poin_dipakai  = doc.get("poin_dipakai", 0),
        poin_dapat    = doc.get("poin_dapat", 0),
        cabang        = doc["cabang"],
        customer_type = doc.get("customer_type", "member"),
        customer_nama = doc.get("customer_nama", ""),
        customer_kontak = doc.get("customer_kontak", ""),
        sp_items      = doc.get("sp_items"),
        foto_serah_terima=doc.get("foto_serah_terima"),
        dibatalkan_at     = fmt_waktu(doc["dibatalkan_at"]) if doc.get("dibatalkan_at") else None,
        dibatalkan_oleh   = doc.get("dibatalkan_oleh"),
        dibatalkan_alasan = doc.get("dibatalkan_alasan"),
        harga_jual_asli   = doc.get("harga_jual_asli"),
        diamandemen_oleh  = doc.get("diamandemen_oleh"),
        diamandemen_at    = fmt_waktu(doc["diamandemen_at"]) if doc.get("diamandemen_at") else None,
    )


async def list_transaksi(db, cabang=None, limit=100, skip=0, date_from=None, date_to=None):
    from datetime import datetime, timezone, timedelta
    query: dict = {}
    if cabang: query["cabang"] = cabang
    if date_from or date_to:
        wf: dict = {}
        if date_from: wf["$gte"] = datetime.fromisoformat(date_from.replace("Z","")).replace(tzinfo=timezone.utc)
        if date_to:
            # Make date_to inclusive by adding 1 day
            dt = datetime.fromisoformat(date_to.replace("Z","")).replace(tzinfo=timezone.utc) + timedelta(days=1)
            wf["$lt"] = dt
        query["waktu"] = wf
    total = await db.transaksi.count_documents(query)
    docs = await db.transaksi.find(query).sort("waktu", -1).skip(skip).limit(limit).to_list(length=limit)
    return [_fmt(d) for d in docs], total


async def create_transaksi(
    db, payload: TransaksiCreateRequest, kasir_name: str, cabang: str,
    poin_dipakai: int = 0,
) -> TransaksiResponse:
    """Transaksi gabungan: HP dan/atau sparepart."""
    has_unit = bool(payload.unit_id and payload.unit_id.strip())
    has_sp = bool(payload.sparepart_items and len(payload.sparepart_items) > 0)

    if not has_unit and not has_sp:
        raise HTTPException(status_code=422, detail="Pilih minimal 1 unit atau sparepart")

    unit = None
    unit_label_parts = []
    total_jual_unit = 0
    total_modal_unit = 0
    sp_labels = []
    sp_total_jual = 0
    sp_total_modal = 0
    sp_items_doc = []

    # Tracks what's already been mutated in this call so we can compensate if
    # a later step fails — otherwise a unit can end up "Sold" with no
    # transaksi record, or sparepart stock can be partially decremented with
    # nothing to show for it (see BUG-010 / BUG-011). Everything from here
    # through the final insert_one runs inside one try block so ANY failure
    # (unit claim, sparepart stock, customer/points validation) triggers the
    # same rollback.
    sp_decremented: list = []  # [(sp_id, jumlah), ...]

    try:
        # ── Process unit (if any) ──
        if has_unit:
            # Atomic claim with cabang — prevents cross-branch sale + double-click
            unit = await db.units.find_one_and_update(
                {"unit_id": payload.unit_id, "cabang": cabang, "status": "Tersedia"},
                {"$set": {"status": "Sold", "tgl_terjual": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc)}},
                return_document=False,
            )
            if not unit:
                existing = await db.units.find_one({"unit_id": payload.unit_id})
                if not existing:
                    raise HTTPException(status_code=404, detail="Unit tidak ditemukan")
                if existing.get("cabang") != cabang:
                    raise HTTPException(status_code=403, detail="Unit bukan milik cabang kamu")
                raise HTTPException(status_code=409, detail=f"Unit tidak tersedia (status: {existing['status']})")

            # Validate IMEI (after claim, before proceeding)
            if unit.get("imei") and unit["imei"] != "-":
                if payload.imei.strip() != unit["imei"]:
                    raise HTTPException(status_code=422, detail="IMEI tidak sesuai. Periksa kembali.")

            total_jual_unit = unit["harga_jual"] + payload.biaya_garansi
            total_modal_unit = unit["harga_modal"]
            unit_label_parts.append(f"{unit['merk']} {unit['tipe']} {unit['storage']}")

        # ── Process spareparts (if any) ──
        if has_sp:
            for item in payload.sparepart_items:
                sp = await db.sparepart.find_one({"sp_id": item.sp_id})
                if not sp:
                    raise HTTPException(status_code=404, detail=f"Sparepart {item.sp_id} tidak ditemukan")
                if sp.get("cabang") != cabang:
                    raise HTTPException(status_code=403, detail=f"Sparepart {sp['nama']} bukan milik cabangmu")
                sp_jenis = sp.get("jenis") or DEFAULT_SPAREPART_JENIS
                if sp_jenis != "dijual":
                    raise HTTPException(
                        status_code=400,
                        detail=f"{sp['nama']} bukan sparepart untuk dijual (jenis: {sp_jenis}) — sparepart repair hanya bisa dipakai lewat modul Service, equipment tidak dijual per-unit"
                    )

                # Atomic check-and-decrement to prevent race condition
                result = await db.sparepart.find_one_and_update(
                    {"sp_id": item.sp_id, "stok": {"$gte": item.jumlah}},
                    {"$inc": {"stok": -item.jumlah}, "$set": {"updated_at": datetime.now(timezone.utc)}},
                    return_document=False,
                )
                if not result:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Stok {sp['nama']} tidak cukup. Tersedia: {sp['stok']}, diminta: {item.jumlah}"
                    )
                sp_decremented.append((item.sp_id, item.jumlah))

                sp_jual = sp["harga_jual"] * item.jumlah
                sp_modal = sp["harga_beli"] * item.jumlah
                sp_total_jual += sp_jual
                sp_total_modal += sp_modal
                sp_labels.append(f"{sp['nama']} x{item.jumlah}")
                sp_items_doc.append({"sp_id": item.sp_id, "jumlah": item.jumlah, "nama": sp["nama"], "harga": sp["harga_jual"]})

        # ── Calculate totals ──
        harga_jual_base = total_jual_unit + sp_total_jual
        harga_modal_total = total_modal_unit + sp_total_modal
        all_labels = unit_label_parts + sp_labels
        label_combined = " + ".join(all_labels) if all_labels else "Transaksi"

        # ── Guest vs Member logic ──
        customer_type = payload.customer_type if payload.customer_type in ["member", "guest"] else "member"
        customer_id = None
        customer_doc = None
        poin_baru = 0
        harga_jual_final = 0

        if customer_type == "member":
            # ── Member flow: auto-create/find customer, points, verification ──
            if payload.customer_nama and payload.customer_nama.strip():
                customer_doc = await db.customers.find_one({"nama": payload.customer_nama.strip(), "cabang": cabang})
                if customer_doc:
                    customer_id = str(customer_doc["_id"])
                else:
                    new_customer = await create_customer(db,
                                    __import__("app.schemas.customer", fromlist=["CustomerCreateRequest"]).CustomerCreateRequest(
                                        nama=payload.customer_nama.strip(),
                                        kontak=payload.customer_kontak.strip() if payload.customer_kontak else "",
                                        cabang=cabang
                                    ),
                                    actor_id=kasir_name,
                                    actor_name=kasir_name,
                                    actor_role="kasir",
                                    cabang=cabang
                                )
                    customer_id = new_customer.id
                    customer_doc = await db.customers.find_one({"nama": payload.customer_nama.strip(), "cabang": cabang})

            # Points logic for member
            if poin_dipakai < 0:
                raise HTTPException(status_code=400, detail="poin_dipakai tidak boleh negatif")
            if customer_doc and poin_dipakai > 0:
                customer_status = customer_doc.get("status", "Pending")
                if customer_status != "Verified":
                    raise HTTPException(
                        status_code=400,
                        detail=f"Customer status {customer_status}: hanya customer Verified yang bisa klaim poin"
                    )
                diskon_poin = poin_dipakai * 1000
                harga_jual_final = harga_jual_base - diskon_poin
                if harga_jual_final < 0:
                    raise HTTPException(status_code=400, detail="Poin terlalu banyak, harga tidak boleh negatif")
                # Atomic conditional decrement — closes a read-then-write race
                # where two concurrent transactions for the same customer
                # (two kasir tabs, or a retried request) could both read the
                # same stale balance, both pass the check above, and both
                # deduct — overspending the balance. The balance check and
                # the deduction now happen as ONE operation against whatever
                # the live balance actually is at that instant.
                claimed_customer = await db.customers.find_one_and_update(
                    {"_id": customer_doc["_id"], "points": {"$gte": poin_dipakai}},
                    {"$inc": {"points": -poin_dipakai}},
                    return_document=True,
                )
                if not claimed_customer:
                    raise HTTPException(status_code=400, detail="Poin customer tidak cukup")
                customer_doc = claimed_customer
            else:
                harga_jual_final = harga_jual_base

            poin_baru = int(harga_jual_final // 100000)

            if customer_doc and poin_baru != 0:
                await db.customers.update_one(
                    {"_id": customer_doc["_id"]},
                    {"$inc": {"points": poin_baru}}
                )
        else:
            # ── Guest flow: no customer creation, no points, no verification ──
            customer_type = "guest"
            customer_id = None
            customer_doc = None
            poin_dipakai = 0
            poin_baru = 0  # guests have no customer record to bank points into
            harga_jual_final = harga_jual_base

        # ── Determine tipe ──
        if has_unit and has_sp:
            tipe = "gabungan"
        elif has_unit:
            tipe = "unit"
        else:
            tipe = "sparepart"

        doc = {
            "trx_id":        await next_trx_id(db),
            "tipe":          tipe,
            "unit_id":       payload.unit_id if has_unit else None,
            "unit_label":    label_combined,
            "kasir":         kasir_name,
            "harga_jual":    harga_jual_final,
            "harga_modal":   harga_modal_total,
            "profit":        harga_jual_final - harga_modal_total,
            "garansi_hari":  payload.garansi_hari if has_unit else 0,
            "biaya_garansi": payload.biaya_garansi if has_unit else 0,
            "poin_dipakai":  0 if customer_type == "guest" else poin_dipakai,
            "poin_dapat":    poin_baru,
            "waktu":         datetime.now(timezone.utc),
            "catatan":       payload.catatan,
            "cabang":        cabang,
            "customer_type": customer_type,
            "customer_nama":  payload.customer_nama.strip() if payload.customer_nama else "",
            "customer_kontak": payload.customer_kontak.strip() if payload.customer_kontak else "",
            "customer_id":    customer_id,
            "sp_items":      sp_items_doc if has_sp else None,
            "foto_serah_terima": payload.foto_serah_terima,
        }
        result = await db.transaksi.insert_one(doc)
    except HTTPException:
        # Compensate whatever was already claimed/decremented before the
        # failure — the customer-points checks above only ever raise before
        # any customer document is mutated, so unit + sparepart is the full
        # set of state that needs reverting here.
        if unit is not None:
            await db.units.update_one(
                {"_id": unit["_id"], "status": "Sold"},
                {"$set": {"status": "Tersedia"}}
            )
        for sp_id, jumlah in sp_decremented:
            await db.sparepart.update_one(
                {"sp_id": sp_id},
                {"$inc": {"stok": jumlah}}
            )
        raise

    doc["_id"] = result.inserted_id
    await write_log(db, kasir_name, "Input Transaksi", f"{doc['trx_id']} • {label_combined}", cabang)
    return _fmt(doc)


async def create_transaksi_sparepart(
    db, payload: TransaksiSparepartRequest, kasir_name: str, cabang: str
) -> TransaksiResponse:
    """Legacy: jual sparepart saja via endpoint /sparepart."""
    if not payload.items:
        raise HTTPException(status_code=422, detail="Minimal 1 item sparepart")

    total_jual  = 0
    total_modal = 0
    labels      = []

    for item in payload.items:
        sp = await db.sparepart.find_one({"sp_id": item.sp_id})
        if not sp:
            raise HTTPException(status_code=404, detail=f"Sparepart {item.sp_id} tidak ditemukan")
        if sp.get("cabang") != cabang:
            raise HTTPException(status_code=403, detail=f"Sparepart {sp['nama']} bukan milik cabangmu")
        sp_jenis = sp.get("jenis") or DEFAULT_SPAREPART_JENIS
        if sp_jenis != "dijual":
            raise HTTPException(
                status_code=400,
                detail=f"{sp['nama']} bukan sparepart untuk dijual (jenis: {sp_jenis})"
            )

        # Atomic check-and-decrement to prevent race condition
        result = await db.sparepart.find_one_and_update(
            {"sp_id": item.sp_id, "stok": {"$gte": item.jumlah}},
            {"$inc": {"stok": -item.jumlah}, "$set": {"updated_at": datetime.now(timezone.utc)}},
            return_document=False,
        )
        if not result:
            raise HTTPException(
                status_code=400,
                detail=f"Stok {sp['nama']} tidak cukup. Tersedia: {sp['stok']}, diminta: {item.jumlah}"
            )

        total_jual  += sp["harga_jual"]  * item.jumlah
        total_modal += sp["harga_beli"]  * item.jumlah
        labels.append(f"{sp['nama']} x{item.jumlah}")

    # Use the same global (non-cabang) counter as create_transaksi above —
    # this endpoint used to mint a per-cabang "JYP-TRX-004" while the main
    # one mints "TRX-005", two ID schemes for the same trx_id field.
    trx_id = await next_trx_id(db)
    now    = datetime.now(timezone.utc)
    label  = ", ".join(labels)
    profit = total_jual - total_modal

    doc = {
        "trx_id":      trx_id,
        "tipe":        "sparepart",
        "unit_id":     None,
        "unit_label":  label,
        "kasir":       kasir_name,
        "harga_jual":  total_jual,
        "harga_modal": total_modal,
        "profit":      profit,
        "waktu":       now,
        "catatan":     payload.catatan,
        "cabang":      cabang,
        "sp_items":    [i.model_dump() for i in payload.items],
    }
    result = await db.transaksi.insert_one(doc)
    doc["_id"] = result.inserted_id
    await write_log(db, kasir_name, "Jual Sparepart", f"{trx_id} • {label}", cabang)
    return _fmt(doc)


async def _void_transaksi_core(db, doc: dict, actor_name: str, reason: str) -> TransaksiResponse:
    """Bagian bersama antara void_transaksi (manual, kasir/KC/owner lewat
    route) dan pemicu otomatis dari cod_service saat COD delivery nego gagal
    di lokasi — membalik semua efek create_transaksi persis sebaliknya:
    unit balik Tersedia, sparepart balik ke stok, dan poin customer (yang
    dipakai dikembalikan, yang didapat ditarik) dalam SATU $inc gabungan.
    Diklaim atomik di sini (bukan di caller) supaya jalur manual dan
    otomatis sama-sama aman dari double-void kalau kebetulan dipicu
    berbarengan."""
    now = datetime.now(timezone.utc)
    trx_id = doc["trx_id"]

    claimed = await db.transaksi.find_one_and_update(
        {"trx_id": trx_id, "dibatalkan_at": None},
        {"$set": {"dibatalkan_at": now, "dibatalkan_oleh": actor_name, "dibatalkan_alasan": reason}},
        return_document=True,
    )
    if not claimed:
        raise HTTPException(409, "Transaksi sudah dibatalkan sebelumnya")
    doc = claimed

    if doc.get("unit_id"):
        await db.units.update_one(
            {"unit_id": doc["unit_id"], "status": "Sold"},
            {"$set": {"status": "Tersedia", "updated_at": now}, "$unset": {"tgl_terjual": ""}},
        )
    for item in (doc.get("sp_items") or []):
        await db.sparepart.update_one(
            {"sp_id": item["sp_id"]},
            {"$inc": {"stok": item["jumlah"]}, "$set": {"updated_at": now}},
        )
    if doc.get("customer_id"):
        poin_delta = doc.get("poin_dipakai", 0) - doc.get("poin_dapat", 0)
        if poin_delta != 0:
            await db.customers.update_one(
                {"_id": ObjectId(doc["customer_id"])},
                {"$inc": {"points": poin_delta}},
            )

    await write_log(db, actor_name, "Batalkan Transaksi", f"{trx_id} dibatalkan — {reason}", doc.get("cabang", ""))
    updated = await db.transaksi.find_one({"trx_id": trx_id})
    return _fmt(updated)


async def void_transaksi(
    db, trx_id: str, actor: str, actor_role: str, reason: str, actor_cabang: str = "",
) -> TransaksiResponse:
    """Kasir/kepala cabang/owner batalkan transaksi yang sudah tercatat —
    dipakai untuk kasus di luar COD (salah input, dibatalkan customer
    sebelum barang dikirim, dll). Ditolak kalau barangnya sudah terkirim ke
    customer lewat COD delivery — membatalkan record di titik itu cuma bikin
    stok "kembali" padahal barangnya sudah fisik di tangan customer; itu
    kasus refund/retur sungguhan (item terpisah, bukan cakupan ini)."""
    if actor_role not in ("kasir", "kepala_cabang", "owner"):
        raise HTTPException(403, "Hanya kasir/kepala cabang/owner yang bisa membatalkan transaksi")
    if not reason or not reason.strip():
        raise HTTPException(422, "Alasan pembatalan wajib diisi")

    doc = await db.transaksi.find_one({"trx_id": trx_id})
    if not doc:
        raise HTTPException(404, f"Transaksi {trx_id} tidak ditemukan")
    if actor_role == "kepala_cabang" and doc.get("cabang") != actor_cabang:
        raise HTTPException(403, "Transaksi bukan milik cabang Anda")
    if actor_role == "kasir" and doc.get("kasir") != actor:
        raise HTTPException(403, "Anda hanya bisa membatalkan transaksi milik Anda sendiri")

    active_cod = await db.cod_requests.find_one({"trx_id": trx_id, "type": "delivery", "status": "terkirim"})
    if active_cod:
        raise HTTPException(409, f"Transaksi ini sudah terkirim ke customer lewat COD ({active_cod['cod_id']}) — tidak bisa dibatalkan dari sini")

    return await _void_transaksi_core(db, doc, actor_name=actor, reason=reason.strip())


async def amend_deal_price(db, trx_id: str, new_harga_jual: int, actor_name: str) -> TransaksiResponse:
    """Nego di lokasi berhasil tapi harga akhir beda dari yang tercatat saat
    transaksi dibuat — dipanggil dari cod_service saat kurir menandai COD
    delivery 'terkirim' dengan deal_price yang berbeda. Modal tidak berubah
    (barang yang sama), jadi selisih harga jual mengalir langsung ke profit.
    poin_dapat dihitung ulang dari harga baru pakai formula yang sama
    seperti create_transaksi (1 poin per Rp100.000), dan selisihnya (bisa
    plus atau minus) di-$inc ke customer sekali saja — bukan reverse-lalu-
    re-apply, supaya tidak ada jendela di mana poin customer sempat salah."""
    now = datetime.now(timezone.utc)
    doc = await db.transaksi.find_one({"trx_id": trx_id})
    if not doc:
        raise HTTPException(404, f"Transaksi {trx_id} tidak ditemukan")
    if doc.get("dibatalkan_at"):
        raise HTTPException(409, "Transaksi ini sudah dibatalkan")
    if new_harga_jual == doc["harga_jual"]:
        return _fmt(doc)

    old_harga_jual = doc["harga_jual"]
    new_profit = new_harga_jual - doc["harga_modal"]
    new_poin_dapat = int(new_harga_jual // 100000) if doc.get("customer_type") == "member" else 0
    poin_delta = new_poin_dapat - doc.get("poin_dapat", 0)

    updated = await db.transaksi.find_one_and_update(
        {"trx_id": trx_id, "dibatalkan_at": None},
        {"$set": {
            "harga_jual": new_harga_jual,
            "profit": new_profit,
            "poin_dapat": new_poin_dapat,
            "harga_jual_asli": doc.get("harga_jual_asli", old_harga_jual),
            "diamandemen_oleh": actor_name,
            "diamandemen_at": now,
            "updated_at": now,
        }},
        return_document=True,
    )
    if not updated:
        raise HTTPException(409, "Transaksi sudah dibatalkan, tidak bisa diubah harganya")

    if doc.get("customer_id") and poin_delta != 0:
        await db.customers.update_one({"_id": ObjectId(doc["customer_id"])}, {"$inc": {"points": poin_delta}})

    await write_log(
        db, actor_name, "Amandemen Harga Transaksi",
        f"{trx_id} • harga Rp{old_harga_jual:,} -> Rp{new_harga_jual:,} (nego di lokasi)",
        doc.get("cabang", ""),
    )
    return _fmt(updated)
