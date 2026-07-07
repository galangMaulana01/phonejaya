# TikTok Scraper - Direct Web Scraping (NO RapidAPI)

## 🎯 Overview

Scraper TikTok **GRATIS** menggunakan public web API TikTok. No RapidAPI, no cost, no limits.

**Cara kerja:**
1. Extract video ID dari URL (vt.tiktok.com, vm.tiktok.com, tiktok.com/@user/video/ID)
2. Fetch metrics via TikTok public web endpoint dengan msToken auth
3. Return: views, likes, comments, shares, author info

---

## 🔑 Prerequisites

### **1. TIKTOK_MS_TOKEN (Wajib)**

Token ini **GRATIS**, didapat dari browser saat login TikTok. Tahan **3-6 bulan**.

**Cara dapetin msToken (2 menit):**

1. Buka browser (Chrome/Edge/Firefox) → Login ke TikTok.com
2. Buka DevTools (F12) → Tab **Network**
3. Refresh halaman TikTok
4. Cari request ke `tiktok.com/api/...` atau `www.tiktok.com`
5. Klik request → Tab **Headers** → Scroll ke **Request Headers**
6. Copy nilai cookie: `msToken=xxxxxxxxxxxxxxxxxxxx`
7. Set di Vercel: **Settings → Environment Variables → `TIKTOK_MS_TOKEN`**

**Format msToken:**
```
msToken=abcd1234-efgh5678-ijkl9012-mnop3456
```

**Catatan:**
- Token berbeda per browser/session
- Kalau expired (error 403), ulangi langkah di atas untuk dapat token baru
- Simpan token di password manager buat backup

---

## 📦 Files

```
/root/phonejaya/app/services/
├── tiktok_scraper.py           ← Scraper utama (direct HTTP)
└── influencer_service.py       ← Updated untuk pakai scraper baru
```

---

## 🔧 Usage

### **1. Fetch Single Video Metrics**

```python
from app.services.tiktok_scraper import fetch_video_metrics

# Input: URL TikTok (any format)
url = "https://vt.tiktok.com/ZSCp675mv/"
metrics = await fetch_video_metrics(url)

# Output:
{
    "video_id": "7384567890123456789",
    "views": 125000,
    "likes": 8500,
    "comments": 342,
    "shares": 156,
    "author_username": "freya",
    "author_nickname": "Freya Official",
    "caption": "Review iphone 15 pro max...",
    "url": "https://www.tiktok.com/@freya/video/7384567890123456789"
}
```

### **2. Fetch User Feed (Multiple Videos)**

```python
from app.services.tiktok_scraper import fetch_user_feed

# Input: @username (tanpa @)
username = "freya"
videos = await fetch_user_feed(username, count=30)

# Output: List[dict] dengan metrics per video
```

---

## 🌐 Supported URL Formats

Scraper support semua format URL TikTok:

| Format | Example | Support |
|--------|---------|---------|
| Short link (vt) | `https://vt.tiktok.com/ZSCp675mv/` | ✅ |
| Short link (vm) | `https://vm.tiktok.com/ZMNabc123/` | ✅ |
| Full URL | `https://www.tiktok.com/@freya/video/7384567890123456789` | ✅ |
| Mobile | `https://m.tiktok.com/v/7384567890123456789.html` | ✅ |

---

## 🚨 Error Handling

Scraper handle semua error dengan graceful fallback:

| Error | Cause | Response |
|-------|-------|----------|
| `403 Forbidden` | msToken expired/invalid | Retry with alternative endpoint, or return 0 metrics + log |
| `404 Not Found` | Video deleted/private | Return 0 metrics + log "Video not found" |
| `Timeout` | Network issue | Retry 2x, then return 0 metrics |
| `Invalid URL` | URL format tidak dikenali | Raise `TikTokScraperError` dengan detail |

**Fallback behavior:**
- Kalau scrape gagal → metrics = 0 (views, likes, comments, shares)
- Error di-log ke `log_service` buat debug
- Video tetap tersimpan di DB, bisa di-retry nanti saat cron sync

---

## 🔄 Integration dengan Influencer Service

### **Create Video (Manual Upload)**

Saat user upload video via frontend:

```python
# influencer_service.py line ~185
if payload.platform.value == "tiktok":
    try:
        metrics = await fetch_tiktok_metrics(str(payload.url))
        views = metrics.get("views", 0)
        likes = metrics.get("likes", 0)
        comments = metrics.get("comments", 0)
        shares = metrics.get("shares", 0)
    except TikTokScraperError as e:
        # Log error, metrics stays 0
        await write_log(db, actor, "TikTok Fetch Failed", str(e), cabang)
```

### **Cron Sync (Auto-Update)**

Cron job `/influencer/sync/cron` jalan tiap jam:

1. Fetch semua influencer dengan `tiktok_username` set
2. Untuk setiap influencer:
   - Fetch feed TikTok (50 video terakhir)
   - Match video by `video_id` atau caption keyword
   - Update metrics untuk video yang udah ada
   - Create video baru kalau match dengan unit
3. Log summary: `TikTok: 15 updated, 3 new`

---

## 📊 Response Schema

```python
{
    "video_id": str,      # TikTok video ID (numeric string)
    "url": str,           # Canonical TikTok URL
    "views": int,         # Play count
    "likes": int,         # Digg count
    "comments": int,      # Comment count
    "shares": int,        # Share count
    "caption": str,       # Video description
    "author_username": str,  # @username
    "author_nickname": str,  # Display name
    "create_time": int,   # Unix timestamp
}
```

---

## 🛠️ Troubleshooting

### **Problem: Semua metrics = 0**

**Check:**
1. `TIKTOK_MS_TOKEN` set di Vercel? → Settings → Environment Variables
2. Token expired? → Coba generate baru (lihat cara di atas)
3. Log error? → Check `/log` endpoint atau MongoDB `logs` collection

**Test manual:**
```bash
# curl test endpoint (setelah deploy)
curl -X GET "https://phonejaya.vercel.app/api/v1/influencer/videos" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### **Problem: 403 Forbidden**

msToken expired atau invalid.

**Fix:**
1. Generate msToken baru dari browser
2. Update `TIKTOK_MS_TOKEN` di Vercel
3. Redeploy (atau tunggu ~5 menit untuk env var propagate)

### **Problem: Video tidak ter-match dengan unit**

Cron sync gagal match video TikTok dengan unit di DB.

**Cause:**
- Caption tidak mengandung unit_id (JYP-IP-BN-001)
- Keyword matching gagal

**Fix:**
- Influencer wajib tag unit_id di caption (misal: "Review iphone 15 | Code: JYP-IP-BN-001")
- ATAU manual update `unit_id` di DB setelah video dibuat

---

## 🔒 Security Notes

- msToken disimpan di **server-side env vars**, never exposed ke frontend
- Scraper hanya fetch public data (no private info)
- Rate limit: ~60 requests/min per IP (TikTok public API limit)
- Cron sync design untuk stay under limit (batch per influencer)

---

## 📝 Maintenance

**Every 3-6 months:**
- Check msToken expiry (monitor 403 errors di log)
- Generate new token kalau perlu (2 menit process)
- Update di Vercel env vars

**No other maintenance needed!** Scraper auto-adapt ke TikTok web API changes.

---

## 🎉 Benefits vs RapidAPI

| Feature | RapidAPI (Old) | Direct Scraper (New) |
|---------|---------------|---------------------|
| Cost | $20-50/month | **FREE** ✅ |
| Rate limit | 500 req/month | **~60 req/min** ✅ |
| Maintenance | Dependent on 3rd party | **Full control** ✅ |
| Setup | API key signup | **Copy msToken from browser** ✅ |
| Reliability | API can be deprecated | **Direct to TikTok** ✅ |

---

## 📚 References

- TikTok Web API: `https://www.tiktok.com/api/post/item_list/`
- msToken docs: TikTok cookie-based auth
- Scraper inspiration: TikTokApi (Playwright-based, tapi kita pakai pure HTTP)

---

**Last updated:** 2026-07-08
**Author:** Hermes Agent (for JAYAPHONE/PHONEJAYA)