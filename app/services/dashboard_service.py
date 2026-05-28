from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.utils.formatters import fmt_waktu


async def get_stats(db: AsyncIOMotorDatabase, cabang: str | None = None) -> dict:
    unit_query = {"cabang": cabang} if cabang else {}
    trx_query  = {"cabang": cabang} if cabang else {}

    # Status counts
    pipeline_status = [{"$match": unit_query}, {"$group": {"_id": "$status", "count": {"$sum": 1}}}]
    status_raw = await db.units.aggregate(pipeline_status).to_list(length=None)
    status_map = {s["_id"]: s["count"] for s in status_raw}
    total_unit = sum(status_map.values())

    # Financial
    pipeline_fin = [{"$match": trx_query}, {"$group": {"_id": None,
        "total_revenue": {"$sum": "$harga_jual"}, "total_modal": {"$sum": "$harga_modal"},
        "total_profit": {"$sum": "$profit"}, "total_trx": {"$sum": 1}}}]
    fin_raw = await db.transaksi.aggregate(pipeline_fin).to_list(length=1)
    fin = fin_raw[0] if fin_raw else {"total_revenue":0,"total_modal":0,"total_profit":0,"total_trx":0}

    # Today profit
    today = datetime.now(timezone.utc).date()
    pipeline_today = [{"$match": {**trx_query, "waktu": {"$gte": datetime(today.year, today.month, today.day, tzinfo=timezone.utc)}}},
                      {"$group": {"_id": None, "profit_hari_ini": {"$sum": "$profit"}}}]
    today_raw = await db.transaksi.aggregate(pipeline_today).to_list(length=1)
    profit_harian = today_raw[0]["profit_hari_ini"] if today_raw else 0

    # Recent transactions
    recent_docs = await db.transaksi.find(trx_query).sort("waktu", -1).limit(5).to_list(length=5)
    recent = [{"id": str(d["_id"]), "trx_id": d["trx_id"], "unit_label": d["unit_label"],
               "kasir": d["kasir"], "harga_jual": d["harga_jual"], "profit": d["profit"],
               "waktu": fmt_waktu(d["waktu"])} for d in recent_docs]

    return {
        "unit": {"total": total_unit, "tersedia": status_map.get("Tersedia",0),
                 "sold": status_map.get("Sold",0), "booking": status_map.get("Booking",0),
                 "service": status_map.get("Service",0)},
        "keuangan": {"total_revenue": fin["total_revenue"], "total_modal": fin["total_modal"],
                     "total_profit": fin["total_profit"], "profit_harian": profit_harian,
                     "total_transaksi": fin["total_trx"]},
        "recent_transaksi": recent,
    }
