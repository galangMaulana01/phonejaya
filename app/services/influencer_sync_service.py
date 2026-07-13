"""
Influencer sync service — runs every hour via cron.
Fetches feeds from TikTok and Instagram for all influencers
and updates metrics / creates new video entries.
NOTE: Facebook support REMOVED - only TikTok and Instagram now
"""
import asyncio
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from motor.motor_asyncio import AsyncIOMotorDatabase
from bson import ObjectId

from app.services.tiktok_feed_scraper import fetch_tiktok_feed, fetch_tiktok_video_metrics, TikTokScraperError
from app.services.instagram_feed_scraper import fetch_instagram_feed, fetch_instagram_post_metrics, InstagramScraperError
# Facebook support REMOVED - only TikTok and Instagram now
from app.utils.id_generator import next_video_id
from app.utils.formatters import fmt_waktu
from app.services.log_service import write_log


async def sync_all_influencers(db: AsyncIOMotorDatabase) -> Dict[str, Any]:
    """
    Main sync function - runs every hour.
    Fetches feeds for all active influencers and updates videos.
    """
    start_time = datetime.now(timezone.utc)
    stats = {
        "tiktok": {"processed": 0, "new": 0, "updated": 0, "errors": 0},
        "instagram": {"processed": 0, "new": 0, "updated": 0, "errors": 0},
        "total_influencers": 0,
        "duration_seconds": 0,
    }
    
    # Get all active influencers with social media usernames (TikTok and Instagram only)
    influencers = await db.users.find({
        "role": "influencer",
        "aktif": True,
        "$or": [
            {"tiktok_username": {"$ne": None, "$ne": ""}},
            {"instagram_username": {"$ne": None, "$ne": ""}},
            # Facebook support REMOVED - facebook_page field kept for backward compatibility
        ]
    }).to_list(length=None)
    
    stats["total_influencers"] = len(influencers)
    
    if not influencers:
        return stats
    
    # Process each influencer
    for influencer in influencers:
        influencer_id = str(influencer["_id"])
        influencer_name = influencer.get("name", "")
        cabang = influencer.get("cabang", "")
        
        # TikTok sync
        if influencer.get("tiktok_username"):
            try:
                await _sync_tiktok(db, influencer_id, influencer_name, cabang, 
                                  influencer["tiktok_username"], stats)
            except Exception as e:
                stats["tiktok"]["errors"] += 1
                await write_log(db, "SYSTEM", "TikTok Sync Error", 
                               f"{influencer_name}: {str(e)[:200]}", cabang)
        
        # Instagram sync
        if influencer.get("instagram_username"):
            try:
                await _sync_instagram(db, influencer_id, influencer_name, cabang,
                                     influencer["instagram_username"], stats)
            except Exception as e:
                stats["instagram"]["errors"] += 1
                await write_log(db, "SYSTEM", "Instagram Sync Error",
                               f"{influencer_name}: {str(e)[:200]}", cabang)
        
        # Facebook sync REMOVED - only TikTok and Instagram now
    
    stats["duration_seconds"] = (datetime.now(timezone.utc) - start_time).total_seconds()
    
    # Log summary
    await write_log(db, "SYSTEM", "Influencer Sync Complete",
        f"TikTok: {stats['tiktok']['updated']} updated, {stats['tiktok']['new']} new | "
        f"IG: {stats['instagram']['updated']} updated, {stats['instagram']['new']} new | "
        f"Errors: {stats['tiktok']['errors']+stats['instagram']['errors']}",
        ""
    )
    
    return stats


async def _sync_tiktok(
    db: AsyncIOMotorDatabase,
    influencer_id: str,
    influencer_name: str,
    cabang: str,
    tiktok_username: str,
    stats: dict
):
    """Sync TikTok feed for one influencer."""
    # Get existing video IDs for this influencer
    existing_videos = {}
    async for v in db.influencer_videos.find({"influencer_id": influencer_id, "platform": "tiktok"}):
        existing_videos[v["video_id"]] = v
    
    # Fetch feed
    videos = await fetch_tiktok_feed(tiktok_username, count=50)
    
    for video_data in videos:
        stats["tiktok"]["processed"] += 1
        video_id = video_data.get("video_id")
        if not video_id:
            continue
        
        if video_id in existing_videos:
            # Update existing video metrics
            await _update_video_metrics(db, existing_videos[video_id], video_data, stats, "tiktok")
        else:
            # Check if we have a matching unit
            await _create_video_from_feed(db, influencer_id, influencer_name, cabang, 
                                         video_data, stats, "tiktok")


async def _sync_instagram(
    db: AsyncIOMotorDatabase,
    influencer_id: str,
    influencer_name: str,
    cabang: str,
    instagram_username: str,
    stats: dict
):
    """Sync Instagram feed for one influencer."""
    existing_videos = {}
    async for v in db.influencer_videos.find({"influencer_id": influencer_id, "platform": "instagram"}):
        existing_videos[v["video_id"]] = v
    
    posts = await fetch_instagram_feed(instagram_username, count=50)
    
    for post_data in posts:
        stats["instagram"]["processed"] += 1
        shortcode = post_data.get("shortcode") or post_data.get("video_id")
        if not shortcode:
            continue
        
        video_id = f"IG-{shortcode}"
        
        if video_id in existing_videos:
            await _update_video_metrics(db, existing_videos[video_id], post_data, stats, "instagram")
        else:
            await _create_video_from_feed(db, influencer_id, influencer_name, cabang,
                                         post_data, stats, "instagram")


# Facebook sync REMOVED - only TikTok and Instagram now


async def _update_video_metrics(
    db: AsyncIOMotorDatabase,
    video: dict,
    feed_data: dict,
    stats: dict,
    platform: str
):
    """Update existing video metrics from feed data."""
    update_data = {
        "updated_at": datetime.now(timezone.utc),
    }
    
    # Map feed data fields to our schema
    if platform == "tiktok":
        update_data["views"] = int(feed_data.get("views", 0))
        update_data["likes"] = int(feed_data.get("likes", 0))
        update_data["comments"] = int(feed_data.get("comments", 0))
    elif platform == "instagram":
        update_data["views"] = int(feed_data.get("views", 0))
        update_data["likes"] = int(feed_data.get("likes", 0))
        update_data["comments"] = int(feed_data.get("comments", 0))
    # Facebook support REMOVED - only TikTok and Instagram now
    
    await db.influencer_videos.update_one(
        {"_id": video["_id"]},
        {"$set": update_data}
    )
    stats[platform]["updated"] += 1


async def _create_video_from_feed(
    db: AsyncIOMotorDatabase,
    influencer_id: str,
    influencer_name: str,
    cabang: str,
    feed_data: dict,
    stats: dict,
    platform: str
):
    """
    Create new video entry from feed data.
    Tries to match with existing unit by caption/unit_id keywords.
    """
    # Extract unit_id from caption or use a placeholder
    unit_id = _extract_unit_id_from_caption(feed_data.get("text", ""), feed_data.get("caption", ""))
    
    # If no unit found, create a placeholder or skip
    # For now, we'll create with a placeholder unit_id
    if not unit_id:
        unit_id = f"UNKNOWN-{feed_data.get('video_id', 'N/A')}"
    
    # Check if unit exists
    unit = await db.units.find_one({"unit_id": unit_id, "cabang": cabang})
    if not unit:
        # Try to find by keywords in caption
        unit = await _find_unit_by_keywords(db, cabang, feed_data.get("text", "") + " " + feed_data.get("caption", ""))
    
    if not unit:
        # No matching unit - log and skip creating video
        await write_log(db, "SYSTEM", f"{platform.title()} Sync - No Unit Match",
                       f"{influencer_name}: {feed_data.get('video_id', 'unknown')}", cabang)
        return
    
    video_id = await next_video_id(db, cabang)
    now = datetime.now(timezone.utc)
    
    unit_label = f"{unit['merk']} {unit['tipe']} {unit['storage']}"
    if unit.get("ram") and unit["ram"] != "-":
        unit_label += f" {unit['ram']}"
    
    # Build video doc
    doc = {
        "video_id": video_id,
        "influencer_id": influencer_id,
        "influencer_name": influencer_name,
        "cabang": cabang,
        "unit_id": unit_id,
        "unit_label": unit_label,
        "platform": platform,
        "url": feed_data.get("url", feed_data.get("post_url", "")),
        "views": feed_data.get("views", 0),
        "likes": feed_data.get("likes", 0),
        "comments": feed_data.get("comments", 0),
        "author_username": feed_data.get("author_username", ""),
        "author_nickname": feed_data.get("author_nickname", feed_data.get("author_full_name", "")),
        "uploaded_at": now,
        "updated_at": now,
        "created_at": now,
    }
    
    await db.influencer_videos.insert_one(doc)
    stats[platform]["new"] += 1
    
    await write_log(db, "SYSTEM", f"{platform.title()} New Video Auto-Created",
                   f"{video_id} → {unit_label} ({platform})", cabang)


def _extract_unit_id_from_caption(*captions: str) -> Optional[str]:
    """Try to extract unit_id from caption text."""
    # Look for patterns like JYP-IP-BN-001
    pattern = r'[A-Z]{2,4}-[A-Z]{2}-[A-Z]{2}-\d{3}'
    for caption in captions:
        if not caption:
            continue
        match = re.search(pattern, caption)
        if match:
            return match.group(0)
    return None


async def _find_unit_by_keywords(db: AsyncIOMotorDatabase, cabang: str, text: str) -> Optional[dict]:
    """Try to find unit by keywords in caption (merk, tipe)."""
    if not text:
        return None
    
    text_lower = text.lower()
    
    # Get all available units in cabang
    units = await db.units.find({"cabang": cabang, "status": "Tersedia"}).to_list(length=None)
    
    for unit in units:
        merk = unit.get("merk", "").lower()
        tipe = unit.get("tipe", "").lower()
        if merk and merk in text_lower:
            if tipe and tipe in text_lower:
                return unit
            # If no tipe match, still return if merk matches uniquely
            merk_matches = [u for u in units if u.get("merk", "").lower() == merk]
            if len(merk_matches) == 1:
                return unit
    
    return None


# Import at bottom to avoid circular imports
import re
from datetime import datetime, timezone