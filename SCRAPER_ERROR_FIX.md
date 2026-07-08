# 🔴 URGENT: TIKTOK SCRAPER ERROR DETECTED

## Test Result (Just Now)

```
Sync Duration: 0.8s
TikTok:    Updated: 0 | New: 0 | Errors: 1 ✗
Instagram: Updated: 0 | New: 0 | Errors: 0
Facebook:  Updated: 0 | New: 0 | Errors: 0
```

## Root Cause

**TikTok scraper error** = `TIKTOK_MS_TOKEN` bermasalah

Kemungkinan:
1. ❌ `TIKTOK_MS_TOKEN` belum set di Vercel
2. ❌ Token expired (biasanya tahan 3-6 bulan)
3. ❌ Token invalid / typo saat copy

## 🔧 FIX NOW (2 MENIT)

### Step 1: Generate msToken Baru

1. Buka browser → Login TikTok.com
2. F12 → Network tab
3. Refresh halaman
4. Cari request ke `tiktok.com` atau `/api/`
5. Klik request → Headers → Request Headers
6. Cari `Cookie:` line
7. Copy value setelah `msToken=` (sampai `;` atau end)

**Example:**
```
Cookie: msToken=abcd1234-efgh5678-ijkl9012-mnop3456; tt_webid=...
                     ↑ COPY DARI SINI
```

### Step 2: Update di Vercel

1. Buka https://vercel.com
2. Pilih project **phonejaya**
3. **Settings** → **Environment Variables**
4. Cari `TIKTOK_MS_TOKEN`
5. Edit / Add dengan token baru
6. Environment: ✅ Production ✅ Preview ✅ Development
7. **Save**

### Step 3: Redeploy

1. **Deployments** → klik deployment terakhir
2. **...** → **Redeploy**
3. Tunggu ~2-3 menit deploy selesai

**Atau** tunggu 5 menitan env var propagate otomatis.

### Step 4: Test Lagi

Setelah redeploy:
1. Login ke dashboard sebagai influencer
2. Buka "Video Saya"
3. Views/likes/comments seharusnya udah ke-fetch!

Atau trigger manual sync via API (butuh owner account).

---

## 📝 Quick Test Command

```bash
# Login
curl -X POST https://phonejaya.vercel.app/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"owner","password":"owner123"}'

# Copy access_token, then:
curl -X POST https://phonejaya.vercel.app/api/v1/influencer/sync \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{}'
```

Expected result after fix:
```json
{
  "data": {
    "tiktok": {"updated": 3, "new": 0, "errors": 0} ✓
  }
}
```

---

## 🐛 If Still Error After This

Check Vercel logs:
1. Vercel → phonejaya → **Functions**
2. Click latest invocation
3. Check logs for error message

Common errors:
- `[403] Access forbidden` → Token expired/wrong
- `[404] User not found` → Wrong username extracted from URL
- `[502] API error` → TikTok server issue (retry later)

---

**Last tested:** 2026-07-08 (just now)  
**Status:** 🔴 NEEDS ATTENTION - TIKTOK_MS_TOKEN INVALID