from datetime import datetime, timezone, timedelta
from typing import Optional, List
from motor.motor_asyncio import AsyncIOMotorDatabase
from fastapi import HTTPException
from bson import ObjectId

from app.schemas.influencer import (
    VideoCreateRequest, VideoUpdateMetricsRequest,
    VideoResponse, InfluencerDashboardStats,
    CatalogItem, InfluencerProfileResponse,
    OwnerInfluencerSummary, OwnerInfluencerDashboard,
    InfluencerSocialUpdate
)
from app.utils.id_generator import next_video_id
from app.utils.formatters import fmt_waktu
from app.services.log_service import write_log
from app.services.tiktok_service import fetch_video_metrics as fetch_tiktok_metrics, TikTokAPIError
from app.services.instagram_service import fetch_post_metrics as fetch_instagram_metrics, InstagramAPIError
from app.services.facebook_service import fetch_post_metrics as fetch_facebook_metrics, FacebookAPIError


def _fmt_video(doc: dict) -> VideoResponse:
    return VideoResponse(
        id=str(doc["_id"]),
        video_id=doc["video_id"],
        influencer_id=doc["influencer_id"],
        influencer_name=doc["influencer_name"],
        cabang=doc["cabang"],
        unit_id=doc["unit_id"],
        unit_label=doc["unit_label"],
        platform=doc["platform"],
        url=doc["url"],
        views=doc.get("views", 0),
        likes=doc.get("likes", 0),
        comments=doc.get("comments", 0),
        shares=doc.get("shares", 0),
        uploaded_at=fmt_waktu(doc.get("uploaded_at", datetime.now(timezone.utc))),
        updated_at=fmt_waktu(doc.get("updated_at", datetime.now(timezone.utc))),
    )


# ════════════════════════════════════════════════════════════════
# INFLUENCER SERVICE (untuk influencer sendiri)
# ════════════════════════════════════════════════════════════════

async def get_dashboard_stats(
    db: AsyncIOMotorDatabase,
    influencer_id: str,
    cabang: str,
    hari: int = 90
) -> InfluencerDashboardStats:
    """Stats dashboard influencer: total video, views, likes, produk dipromosikan, trend, top 5."""
    now = datetime.now(timezone.utc)
    dt_from = now - timedelta(days=hari)

    # Base query
    base_query = {"influencer_id": influencer_id, "cabang": cabang}

    # Total video
    total_video = await db.influencer_videos.count_documents(base_query)

    # Aggregation untuk stats
    pipeline = [
        {"$match": base_query},
        {"$group": {
            "_id": None,
            "total_views": {"$sum": "$views"},
            "total_likes": {"$sum": "$likes"},
            "unit_ids": {"$addToSet": "$unit_id"},
        }}
    ]
    agg_result = await db.influencer_videos.aggregate(pipeline).to_list(length=1)
    total_views = agg_result[0]["total_views"] if agg_result else 0
    total_likes = agg_result[0]["total_likes"] if agg_result else 0
    produk_dipromosikan = len(agg_result[0]["unit_ids"]) if agg_result else 0

    # Trend views per minggu
    trend_pipeline = [
        {"$match": {**base_query, "uploaded_at": {"$gte": dt_from}}},
        {"$group": {
            "_id": {"$dateToString": {"format": "%Y-W%U", "date": "$uploaded_at"}},
            "views": {"$sum": "$views"},
        }},
        {"$sort": {"_id": 1}},
    ]
    trend_docs = await db.influencer_videos.aggregate(trend_pipeline).to_list(length=None)
    trend_views = [{"periode": d["_id"], "views": d["views"]} for d in trend_docs]

    # Top 5 video by views
    top_docs = await db.influencer_videos.find(base_query).sort("views", -1).limit(5).to_list(length=5)
    top_videos = [_fmt_video(d) for d in top_docs]

    return InfluencerDashboardStats(
        total_video=total_video,
        total_views=total_views,
        total_likes=total_likes,
        produk_dipromosikan=produk_dipromosikan,
        trend_views=trend_views,
        top_videos=top_videos,
    )


async def get_catalog(
    db: AsyncIOMotorDatabase,
    cabang: str,
    influencer_id: str,
    kategori: Optional[str] = None,
    q: Optional[str] = None
) -> List[CatalogItem]:
    """Katalog produk Tersedia dari cabang influencer + flag has_video."""
    # Ambil units Tersedia
    query = {"cabang": cabang, "status": "Tersedia"}
    if kategori:
        query["kategori"] = kategori
    if q:
        regex = {"$regex": q, "$options": "i"}
        query["$or"] = [
            {"merk": regex}, {"tipe": regex}, {"unit_id": regex},
            {"storage": regex}, {"warna": regex}
        ]
    units = await db.units.find(query).sort("_id", -1).limit(200).to_list(length=200)

    # Ambil video_ids yang sudah dibuat influencer ini
    video_unit_ids = set()
    video_ids_map = {}
    videos = await db.influencer_videos.find({"influencer_id": influencer_id}).to_list(length=None)
    for v in videos:
        video_unit_ids.add(v["unit_id"])
        video_ids_map[v["unit_id"]] = v["video_id"]

    # Build catalog items
    items = []
    for u in units:
        has_vid = u["unit_id"] in video_unit_ids
        items.append(CatalogItem(
            unit_id=u["unit_id"],
            merk=u["merk"],
            tipe=u["tipe"],
            storage=u["storage"],
            warna=u["warna"],
            harga_jual=u["harga_jual"],
            kategori=u["kategori"],
            has_video=has_vid,
            video_id=video_ids_map.get(u["unit_id"])
        ))
    return items


async def create_video(
    db: AsyncIOMotorDatabase,
    payload: VideoCreateRequest,
    influencer_id: str,
    influencer_name: str,
    cabang: str,
    actor: str
) -> VideoResponse:
    """Buat video baru untuk unit. Auto-fetch metrics dari TikTok API jika platform TikTok."""
    # Cek unit
    unit = await db.units.find_one({"unit_id": payload.unit_id, "cabang": cabang, "status": "Tersedia"})
    if not unit:
        raise HTTPException(status_code=404, detail="Unit tidak ditemukan atau tidak Tersedia di cabang Anda")

    # Cek sudah ada video untuk unit ini oleh influencer ini
    existing = await db.influencer_videos.find_one({
        "influencer_id": influencer_id,
        "unit_id": payload.unit_id
    })
    if existing:
        raise HTTPException(status_code=409, detail="Anda sudah membuat video untuk unit ini")

    video_id = await next_video_id(db, cabang)
    now = datetime.now(timezone.utc)
    uploaded_at = now  # default now, bisa di-override nanti

    unit_label = f"{unit['merk']} {unit['tipe']} {unit['storage']}"
    if unit.get("ram") and unit["ram"] != "-":
        unit_label += f" {unit['ram']}"

    # Default metrics
    views = likes = comments = shares = 0
    author_username = ""
    author_nickname = ""

    # Auto-fetch metrics berdasarkan platform
    if payload.platform.value == "tiktok":
        try:
            metrics = await fetch_tiktok_metrics(str(payload.url))
            views = metrics.get("views", 0)
            likes = metrics.get("likes", 0)
            comments = metrics.get("comments", 0)
            shares = metrics.get("shares", 0)
            author_username = metrics.get("author_username", "")
            author_nickname = metrics.get("author_nickname", "")
        except TikTokAPIError as e:
            await write_log(
                db, actor, "TikTok Auto-Fetch Failed",
                f"{video_id} → {e.args[0] if e.args else 'Unknown error'}",
                cabang
            )
    elif payload.platform.value == "instagram":
        try:
            metrics = await fetch_instagram_metrics(str(payload.url))
            views = metrics.get("views", 0)
            likes = metrics.get("likes", 0)
            comments = metrics.get("comments", 0)
            shares = 0  # Instagram doesn't expose shares via public API
            author_username = metrics.get("owner", {}).get("username", "")
            author_nickname = metrics.get("owner", {}).get("full_name", "")
        except InstagramAPIError as e:
            await write_log(
                db, actor, "Instagram Auto-Fetch Failed",
                f"{video_id} → {e.args[0] if e.args else 'Unknown error'}",
                cabang
            )
    elif payload.platform.value == "facebook":
        try:
            metrics = await fetch_facebook_metrics(str(payload.url))
            views = metrics.get("views", 0)
            likes = metrics.get("likes", 0)
            comments = metrics.get("comments", 0)
            shares = metrics.get("shares", 0)
            author_username = metrics.get("page_name", "")
            author_nickname = metrics.get("page_name", "")
        except FacebookAPIError as e:
            await write_log(
                db, actor, "Facebook Auto-Fetch Failed",
                f"{video_id} → {e.args[0] if e.args else 'Unknown error'}",
                cabang
            )

    doc = {
        "video_id": video_id,
        "influencer_id": influencer_id,
        "influencer_name": influencer_name,
        "cabang": cabang,
        "unit_id": payload.unit_id,
        "unit_label": unit_label,
        "platform": payload.platform.value,
        "url": payload.url,
        "views": views,
        "likes": likes,
        "comments": comments,
        "shares": shares,
        "author_username": author_username,
        "author_nickname": author_nickname,
        "uploaded_at": uploaded_at,
        "updated_at": now,
        "created_at": now,
    }

    result = await db.influencer_videos.insert_one(doc)
    doc["_id"] = result.inserted_id

    await write_log(
        db, actor, "Buat Video Influencer",
        f"{video_id} → {unit_label} ({payload.platform.value})" + (f" [auto-fetched: {views} views]" if views else " [manual]"),
        cabang
    )

    return _fmt_video(doc)


async def list_videos(
    db: AsyncIOMotorDatabase,
    influencer_id: str,
    cabang: str,
    platform: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 100
) -> List[VideoResponse]:
    """List video influencer dengan filter."""
    query = {"influencer_id": influencer_id, "cabang": cabang}
    if platform:
        query["platform"] = platform
    if date_from or date_to:
        from datetime import datetime, timezone
        wf = {}
        if date_from:
            wf["$gte"] = datetime.fromisoformat(date_from.replace("Z", "")).replace(tzinfo=timezone.utc)
        if date_to:
            wf["$lte"] = datetime.fromisoformat(date_to.replace("Z", "")).replace(tzinfo=timezone.utc)
        query["uploaded_at"] = wf

    docs = await db.influencer_videos.find(query).sort("uploaded_at", -1).limit(limit).to_list(length=limit)
    return [_fmt_video(d) for d in docs]


async def update_video_metrics(
    db: AsyncIOMotorDatabase,
    video_id: str,
    payload: VideoUpdateMetricsRequest,
    influencer_id: str,
    actor: str
) -> VideoResponse:
    """Update metrics video (views, likes, comments, shares). Hanya pemilik video."""
    video = await db.influencer_videos.find_one({"video_id": video_id})
    if not video:
        raise HTTPException(status_code=404, detail="Video tidak ditemukan")
    if video["influencer_id"] != influencer_id:
        raise HTTPException(status_code=403, detail="Bukan video Anda")

    update_data = {"updated_at": datetime.now(timezone.utc)}
    if payload.views is not None:
        update_data["views"] = payload.views
    if payload.likes is not None:
        update_data["likes"] = payload.likes
    if payload.comments is not None:
        update_data["comments"] = payload.comments
    if payload.shares is not None:
        update_data["shares"] = payload.shares

    await db.influencer_videos.update_one(
        {"video_id": video_id},
        {"$set": update_data}
    )

    await write_log(
        db, actor, "Update Metrics Video",
        f"{video_id} → views:{update_data.get('views', video['views'])} likes:{update_data.get('likes', video['likes'])}",
        video["cabang"]
    )

    updated = await db.influencer_videos.find_one({"video_id": video_id})
    return _fmt_video(updated)


async def get_profile(db: AsyncIOMotorDatabase, influencer_id: str) -> InfluencerProfileResponse:
    """Ambil profil influencer dari users collection (basic info + social media)."""
    try:
        user = await db.users.find_one({"_id": ObjectId(influencer_id)})
    except Exception:
        user = None
    if not user:
        raise HTTPException(status_code=404, detail="Influencer tidak ditemukan")
    return InfluencerProfileResponse(
        id=str(user["_id"]),
        name=user.get("name", ""),
        username=user.get("username", ""),
        cabang=user.get("cabang", ""),
        tiktok_username=user.get("tiktok_username"),
        instagram_username=user.get("instagram_username"),
        facebook_page=user.get("facebook_page"),
    )


async def update_influencer_social(db: AsyncIOMotorDatabase, influencer_id: str, payload: InfluencerSocialUpdate, actor: str) -> InfluencerProfileResponse:
    """Update social media usernames untuk influencer."""
    try:
        oid = ObjectId(influencer_id)
    except Exception:
        raise HTTPException(status_code=400, detail="ID influencer tidak valid")
    
    update_data = {}
    if payload.tiktok_username is not None:
        update_data["tiktok_username"] = payload.tiktok_username
    if payload.instagram_username is not None:
        update_data["instagram_username"] = payload.instagram_username
    if payload.facebook_page is not None:
        update_data["facebook_page"] = payload.facebook_page
    
    if not update_data:
        raise HTTPException(status_code=422, detail="Tidak ada data yang diupdate")
    
    update_data["updated_at"] = datetime.now(timezone.utc)
    
    await db.users.update_one({"_id": oid}, {"$set": update_data})
    await write_log(
        db, actor, "Update Influencer Social",
        f"{influencer_id} → tiktok:{payload.tiktok_username} ig:{payload.instagram_username} fb:{payload.facebook_page}",
        ""
    )
    
    updated_user = await db.users.find_one({"_id": oid})
    return InfluencerProfileResponse(
        id=str(updated_user["_id"]),
        name=updated_user.get("name", ""),
        username=updated_user.get("username", ""),
        cabang=updated_user.get("cabang", ""),
        tiktok_username=updated_user.get("tiktok_username"),
        instagram_username=updated_user.get("instagram_username"),
        facebook_page=updated_user.get("facebook_page"),
    )


# ════════════════════════════════════════════════════════════════
# OWNER INFLUENCER MONITOR SERVICE
# ════════════════════════════════════════════════════════════════

async def get_owner_dashboard(db: AsyncIOMotorDatabase) -> OwnerInfluencerDashboard:
    """Dashboard owner: agregat semua influencer."""
    # Total influencers
    total_influencers = await db.users.count_documents({"role": "influencer", "aktif": True})

    # Total videos
    total_videos = await db.influencer_videos.count_documents({})

    # Aggregation stats
    pipeline = [
        {"$group": {
            "_id": None,
            "total_views": {"$sum": "$views"},
            "total_likes": {"$sum": "$likes"},
        }}
    ]
    agg = await db.influencer_videos.aggregate(pipeline).to_list(length=1)
    total_views = agg[0]["total_views"] if agg else 0
    total_likes = agg[0]["total_likes"] if agg else 0

    # By cabang
    cabang_pipeline = [
        {"$group": {
            "_id": "$cabang",
            "video_count": {"$sum": 1},
            "views": {"$sum": "$views"},
            "likes": {"$sum": "$likes"},
            "influencers": {"$addToSet": "$influencer_id"},
        }},
        {"$project": {
            "cabang": "$_id",
            "video_count": 1,
            "views": 1,
            "likes": 1,
            "influencer_count": {"$size": "$influencers"},
        }},
        {"$sort": {"video_count": -1}}
    ]
    by_cabang = await db.influencer_videos.aggregate(cabang_pipeline).to_list(length=None)

    # Top influencers
    inf_pipeline = [
        {"$group": {
            "_id": "$influencer_id",
            "influencer_name": {"$first": "$influencer_name"},
            "cabang": {"$first": "$cabang"},
            "total_video": {"$sum": 1},
            "total_views": {"$sum": "$views"},
            "total_likes": {"$sum": "$likes"},
            "unit_ids": {"$addToSet": "$unit_id"},
            "last_upload": {"$max": "$uploaded_at"},
        }},
        {"$project": {
            "influencer_id": "$_id",
            "influencer_name": 1,
            "cabang": 1,
            "total_video": 1,
            "total_views": 1,
            "total_likes": 1,
            "produk_dipromosikan": {"$size": "$unit_ids"},
            "last_upload": 1,
        }},
        {"$sort": {"total_views": -1}},
        {"$limit": 10}
    ]
    top_inf = await db.influencer_videos.aggregate(inf_pipeline).to_list(length=10)
    top_influencers = [OwnerInfluencerSummary(**d) for d in top_inf]

    # Recent videos (all)
    recent = await db.influencer_videos.find().sort("uploaded_at", -1).limit(10).to_list(length=10)
    recent_videos = [_fmt_video(d) for d in recent]

    return OwnerInfluencerDashboard(
        total_influencers=total_influencers,
        total_videos=total_videos,
        total_views=total_views,
        total_likes=total_likes,
        by_cabang=by_cabang,
        top_influencers=top_influencers,
        recent_videos=recent_videos,
    )


async def list_all_videos_owner(
    db: AsyncIOMotorDatabase,
    cabang: Optional[str] = None,
    influencer_id: Optional[str] = None,
    platform: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 200
) -> List[VideoResponse]:
    """Owner lihat semua video dengan filter."""
    query = {}
    if cabang:
        query["cabang"] = cabang
    if influencer_id:
        query["influencer_id"] = influencer_id
    if platform:
        query["platform"] = platform
    if date_from or date_to:
        from datetime import datetime, timezone
        wf = {}
        if date_from:
            wf["$gte"] = datetime.fromisoformat(date_from.replace("Z", "")).replace(tzinfo=timezone.utc)
        if date_to:
            wf["$lte"] = datetime.fromisoformat(date_to.replace("Z", "")).replace(tzinfo=timezone.utc)
        query["uploaded_at"] = wf

    docs = await db.influencer_videos.find(query).sort("uploaded_at", -1).limit(limit).to_list(length=limit)
    return [_fmt_video(d) for d in docs]


async def list_influencers(db: AsyncIOMotorDatabase) -> List[dict]:
    """List semua influencer untuk dropdown filter owner."""
    users = await db.users.find({"role": "influencer", "aktif": True}).to_list(length=None)
    return [
        {"influencer_id": u["username"], "name": u.get("name", ""), "cabang": u.get("cabang", "")}
        for u in users
    ]