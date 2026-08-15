from datetime import datetime, timezone
import re
from typing import Optional, List
from motor.motor_asyncio import AsyncIOMotorDatabase
from bson import ObjectId
from fastapi import HTTPException
from app.schemas.customer import (
    CustomerCreateRequest, CustomerVerifyRequest, CustomerRejectRequest,
    CustomerResubmitRequest, CustomerResponse, CustomerListItem, CustomerStatusEnum
)
from app.utils.formatters import fmt_waktu
from app.services.log_service import write_log


def _fmt(doc: dict) -> CustomerResponse:
    # Convert status_history timestamps to string format
    status_history = doc.get("status_history", [])
    formatted_history = []
    for h in status_history:
        h_copy = dict(h)
        if "timestamp" in h_copy and isinstance(h_copy["timestamp"], datetime):
            h_copy["timestamp"] = fmt_waktu(h_copy["timestamp"])
        formatted_history.append(h_copy)

    return CustomerResponse(
        id=str(doc["_id"]),
        nama=doc["nama"],
        kontak=doc["kontak"],
        cabang=doc.get("cabang", ""),
        status=doc.get("status", "Pending"),
        points=doc.get("points", 0),
        created_at=fmt_waktu(doc.get("created_at")),
        verified_at=fmt_waktu(doc.get("verified_at")) if doc.get("verified_at") else None,
        verified_by=doc.get("verified_by"),
        rejected_at=fmt_waktu(doc.get("rejected_at")) if doc.get("rejected_at") else None,
        rejected_by=doc.get("rejected_by"),
        rejected_reason=doc.get("rejected_reason"),
        status_history=formatted_history,
    )


def _fmt_list(doc: dict) -> CustomerListItem:
    return CustomerListItem(
        id=str(doc["_id"]),
        nama=doc["nama"],
        kontak=doc["kontak"],
        cabang=doc.get("cabang", ""),
        status=doc.get("status", "Pending"),
        points=doc.get("points", 0),
        created_at=fmt_waktu(doc.get("created_at")),
        verified_at=fmt_waktu(doc.get("verified_at")) if doc.get("verified_at") else None,
        verified_by=doc.get("verified_by"),
        rejected_at=fmt_waktu(doc.get("rejected_at")) if doc.get("rejected_at") else None,
        rejected_by=doc.get("rejected_by"),
        rejected_reason=doc.get("rejected_reason"),
    )


async def _add_status_history(
    db: AsyncIOMotorDatabase,
    customer_id: ObjectId,
    status_lama: str,
    status_baru: str,
    actor_id: str,
    actor_name: str,
    actor_role: str,
    reason: str = "",
) -> None:
    """Add status history entry to customer document."""
    history_entry = {
        "status_lama": status_lama,
        "status_baru": status_baru,
        "actor_id": actor_id,
        "actor_name": actor_name,
        "actor_role": actor_role,
        "timestamp": datetime.now(timezone.utc),
        "reason": reason if reason else None,
    }
    await db.customers.update_one(
        {"_id": customer_id},
        {"$push": {"status_history": history_entry}}
    )


async def create_customer(
    db: AsyncIOMotorDatabase,
    payload: CustomerCreateRequest,
    actor_id: str,
    actor_name: str,
    actor_role: str,
    cabang: str,
) -> CustomerResponse:
    # Check duplicate kontak per cabang
    existing = await db.customers.find_one({"kontak": payload.kontak, "cabang": cabang})
    if existing:
        raise HTTPException(409, "Nomor kontak sudah terdaftar di cabang ini")

    now = datetime.now(timezone.utc)
    doc = {
        "nama": payload.nama,
        "kontak": payload.kontak,
        "cabang": cabang,
        "status": "Pending",
        "points": 0,
        "created_at": now,
        "created_by": actor_id,
        "created_by_name": actor_name,
        "created_by_role": actor_role,
        "status_history": [{
            "status_lama": "",
            "status_baru": "Pending",
            "actor_id": actor_id,
            "actor_name": actor_name,
            "actor_role": actor_role,
            "timestamp": now,
            "reason": None,
        }],
    }
    result = await db.customers.insert_one(doc)
    doc["_id"] = result.inserted_id

    await write_log(
        db, actor_id, "Tambah Customer",
        f"{payload.nama} ({payload.kontak}) - Pending", cabang
    )

    return _fmt(doc)


async def list_customers(
    db: AsyncIOMotorDatabase,
    cabang: Optional[str] = None,
    status: Optional[str] = None,
    q: Optional[str] = None,
) -> List[CustomerListItem]:
    query: dict = {}
    if cabang:
        query["cabang"] = cabang
    if status:
        query["status"] = status
    if q:
        regex = {"$regex": re.escape(q), "$options": "i"}
        query["$or"] = [{"nama": regex}, {"kontak": regex}]

    docs = await db.customers.find(query).sort("created_at", -1).to_list(length=200)
    return [_fmt_list(d) for d in docs]


async def get_customer_detail(
    db: AsyncIOMotorDatabase,
    customer_id: str,
) -> CustomerResponse:
    doc = await db.customers.find_one({"_id": ObjectId(customer_id)})
    if not doc:
        raise HTTPException(404, "Customer tidak ditemukan")
    return _fmt(doc)


async def _validate_transition(
    current_status: str,
    target_status: str,
    actor_role: str,
) -> None:
    """Strict state machine validation."""
    allowed_transitions = {
        "Pending": ["Verified", "Rejected"],
        "Rejected": ["Pending"],  # Resubmit
    }

    if current_status not in allowed_transitions:
        raise HTTPException(400, f"Status {current_status} tidak bisa diubah")

    if target_status not in allowed_transitions[current_status]:
        raise HTTPException(
            400,
            f"Transisi dari {current_status} ke {target_status} tidak diizinkan"
        )

    # Authorization check
    if target_status in ["Verified", "Rejected"] and actor_role not in ["kepala_cabang", "owner"]:
        raise HTTPException(403, "Hanya Kepala Cabang atau Owner yang bisa approve/reject")

    if target_status == "Pending" and actor_role not in ["kasir", "teknisi", "kepala_cabang", "owner"]:
        raise HTTPException(403, "Hanya Kasir/Teknisi/Kepala Cabang/Owner yang bisa resubmit")


async def _add_status_history(
    db: AsyncIOMotorDatabase,
    customer_id: ObjectId,
    status_lama: str,
    status_baru: str,
    actor_id: str,
    actor_name: str,
    actor_role: str,
    reason: str = "",
) -> None:
    """Add status history entry to customer document."""
    history_entry = {
        "status_lama": status_lama,
        "status_baru": status_baru,
        "actor_id": actor_id,
        "actor_name": actor_name,
        "actor_role": actor_role,
        "timestamp": datetime.now(timezone.utc),
        "reason": reason if reason else None,
    }
    await db.customers.update_one(
        {"_id": customer_id},
        {"$push": {"status_history": history_entry}}
    )


async def approve_customer(
    db: AsyncIOMotorDatabase,
    customer_id: str,
    actor_id: str,
    actor_name: str,
    actor_role: str,
    actor_cabang: str = "",
) -> CustomerResponse:
    doc = await db.customers.find_one({"_id": ObjectId(customer_id)})
    if not doc:
        raise HTTPException(404, "Customer tidak ditemukan")

    if actor_role != "owner" and doc.get("cabang") != actor_cabang:
        raise HTTPException(403, "Bukan hak anda untuk memverifikasi customer ini")

    current_status = doc.get("status", "Pending")
    await _validate_transition(current_status, "Verified", actor_role)

    update = {
        "status": "Verified",
        "verified_at": datetime.now(timezone.utc),
        "verified_by": actor_id,
        "verified_by_name": actor_name,
        "verified_by_role": actor_role,
    }

    # Atomic claim on the status we just validated against — if a concurrent
    # approve/reject already moved this customer, this matches 0 docs instead
    # of both callers writing a duplicate status_history entry (BUG-020).
    claimed = await db.customers.find_one_and_update(
        {"_id": ObjectId(customer_id), "status": current_status},
        {"$set": update},
    )
    if not claimed:
        raise HTTPException(409, "Status customer sudah berubah oleh proses lain, silakan refresh.")

    # Add status history
    await _add_status_history(
        db, ObjectId(customer_id), current_status, "Verified",
        actor_id, actor_name, actor_role, ""
    )

    updated = await db.customers.find_one({"_id": ObjectId(customer_id)})

    await write_log(
        db, actor_id, "Approve Customer",
        f"{doc['nama']} diverifikasi", doc.get("cabang", "")
    )

    return _fmt(updated)


async def reject_customer(
    db: AsyncIOMotorDatabase,
    customer_id: str,
    reason: str,
    actor_id: str,
    actor_name: str,
    actor_role: str,
    actor_cabang: str = "",
) -> CustomerResponse:
    doc = await db.customers.find_one({"_id": ObjectId(customer_id)})
    if not doc:
        raise HTTPException(404, "Customer tidak ditemukan")

    if actor_role != "owner" and doc.get("cabang") != actor_cabang:
        raise HTTPException(403, "Bukan hak anda untuk menolak customer ini")

    current_status = doc.get("status", "Pending")
    await _validate_transition(current_status, "Rejected", actor_role)

    if not reason or not reason.strip():
        raise HTTPException(400, "Alasan reject wajib diisi")

    update = {
        "status": "Rejected",
        "rejected_at": datetime.now(timezone.utc),
        "rejected_by": actor_id,
        "rejected_by_name": actor_name,
        "rejected_by_role": actor_role,
        "rejected_reason": reason.strip(),
    }

    claimed = await db.customers.find_one_and_update(
        {"_id": ObjectId(customer_id), "status": current_status},
        {"$set": update},
    )
    if not claimed:
        raise HTTPException(409, "Status customer sudah berubah oleh proses lain, silakan refresh.")

    # Add status history
    await _add_status_history(
        db, ObjectId(customer_id), current_status, "Rejected",
        actor_id, actor_name, actor_role, reason.strip()
    )

    updated = await db.customers.find_one({"_id": ObjectId(customer_id)})

    await write_log(
        db, actor_id, "Reject Customer",
        f"{doc['nama']} ditolak: {reason}", doc.get("cabang", "")
    )

    return _fmt(updated)


async def resubmit_customer(
    db: AsyncIOMotorDatabase,
    customer_id: str,
    actor_id: str,
    actor_name: str,
    actor_role: str,
) -> CustomerResponse:
    doc = await db.customers.find_one({"_id": ObjectId(customer_id)})
    if not doc:
        raise HTTPException(404, "Customer tidak ditemukan")

    current_status = doc.get("status", "Pending")
    await _validate_transition(current_status, "Pending", actor_role)

    if current_status != "Rejected":
        raise HTTPException(400, "Hanya customer Rejected yang bisa di-resubmit")

    update = {
        "status": "Pending",
        "resubmitted_at": datetime.now(timezone.utc),
        "resubmitted_by": actor_id,
        "resubmitted_by_name": actor_name,
        "resubmitted_by_role": actor_role,
    }
    # Clear the previous rejection's metadata — otherwise it survives a later
    # approval and CustomerResponse keeps showing a stale rejected_reason
    # alongside status: Verified (BUG-019).
    unset_fields = {
        "rejected_at": "", "rejected_by": "", "rejected_by_name": "",
        "rejected_by_role": "", "rejected_reason": "",
    }

    claimed = await db.customers.find_one_and_update(
        {"_id": ObjectId(customer_id), "status": current_status},
        {"$set": update, "$unset": unset_fields},
    )
    if not claimed:
        raise HTTPException(409, "Status customer sudah berubah oleh proses lain, silakan refresh.")

    # Add status history
    await _add_status_history(
        db, ObjectId(customer_id), current_status, "Pending",
        actor_id, actor_name, actor_role, "Resubmit after rejection"
    )

    updated = await db.customers.find_one({"_id": ObjectId(customer_id)})

    await write_log(
        db, actor_id, "Resubmit Customer",
        f"{doc['nama']} diajukan ulang", doc.get("cabang", "")
    )

    return _fmt(updated)


async def get_pending_count(
    db: AsyncIOMotorDatabase,
    cabang: Optional[str] = None,
) -> int:
    query = {"status": "Pending"}
    if cabang:
        query["cabang"] = cabang
    return await db.customers.count_documents(query)