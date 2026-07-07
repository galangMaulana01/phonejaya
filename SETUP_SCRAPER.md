# 🚀 SETUP SCRAPER TIKTOK - QUICK GUIDE

## ✅ STATUS IMPLEMENTASI

**DONE:**
- ✅ `tiktok_scraper.py` - Direct scraper (no RapidAPI, no cost)
- ✅ `influencer_service.py` - Updated pakai scraper baru
- ✅ `TIKTOKSCRAPER.md` - Dokumentasi lengkap
- ✅ Error handling + logging

**TODO:**
- ⏳ Set `TIKTOK_MS_TOKEN` di Vercel (2 menit)
- ⏳ Test fetch metrics
- ⏳ Trigger manual sync untuk update video lama

---

## 🔑 CARA DAPETIN msToken (2 MENIT)

### **Step 1: Buka TikTok di Browser**
1. Buka Chrome/Firefox/Edge
2. Login ke https://www.tiktok.com (pakai akun TikTok lo)

### **Step 2: Buka DevTools**
1. Tekan **F12** (atau klik kanan → Inspect)
2. Tab **Network**
3. Centang **Preserve log**

### **Step 3: Refresh Halaman**
1. Refresh TikTok (F5)
2. Di Network tab, cari request ke `www.tiktok.com`

### **Step 4: Copy msToken**
1. Klik request ke `www.tiktok.com` atau `/api/post/item_list/`
2. Tab **Headers** → Scroll ke **Request Headers**
3. Cari cookie: `msToken=xxxxxxxxxxxxxxxxxxxx`
4. **Copy nilai setelah `msToken=`** (sampai `;` atau end of string)

**Example:**
```
Cookie: msToken=abcd1234-efgh5678-ijkl9012-mnop3456; tt_webid=12345...
                      ↑ COPY DARI SINI SAMPAI SEBELUM ;
```

### **Step 5: Set di Vercel**
1. Buka https://vercel.com
2. Pilih project **phonejaya**
3. **Settings** → **Environment Variables**
4. **Add Variable**:
   - Name: `TIKTOK_MS_TOKEN`
   - Value: `<paste token lo>`
   - Environment: ✅ Production ✅ Preview ✅ Development
5. **Save**

### **Step 6: Redeploy (atau tunggu)**
- Env var baru butuh ~5 menit untuk propagate
- Atau manual redeploy: **Deployments** → **Redeploy**

---

## 🧪 TESTING SETELAH SETUP

### **Test 1: Login sebagai Influencer**
```bash
curl -X POST https://phonejaya.vercel.app/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"freya","password":"freya123"}'
```

### **Test 2: Manual Trigger Sync**
```bash
curl -X POST https://phonejaya.vercel.app/api/v1/influencer/sync \
  -H "Authorization: Bearer <YOUR_TOKEN>"
```

### **Test 3: Check Video Metrics**
```bash
curl -X GET "https://phonejaya.vercel.app/api/v1/influencer/videos?limit=10" \
  -H "Authorization: Bearer <YOUR_TOKEN>"
```

**Expected result:**
```json
{
  "data": [
    {
      "video_id": "BDG-VID-002",
      "platform": "tiktok",
      "views": 125000,  ← SEHARUSNYA GA 0 LAGI!
      "likes": 8500,
      "comments": 342
    }
  ]
}
```

---

## 🐛 TROUBLESHOOTING

### **Error: 403 Forbidden**
**Cause:** msToken expired atau invalid

**Fix:**
1. Generate msToken baru (ulang Step 1-4)
2. Update di Vercel
3. Redeploy

### **Error: 500 - TIKTOK_MS_TOKEN not configured**
**Cause:** Env var belum set atau belum propagate

**Fix:**
1. Check di Vercel → Settings → Environment Variables
2. Pastikan `TIKTOK_MS_TOKEN` ada dan value-nya bener
3. Tunggu 5-10 menit atau redeploy

### **Video metrics masih 0**
**Cause:** Cron sync belum jalan atau fetch gagal

**Fix:**
1. Trigger manual sync (Test 2 di atas)
2. Check log: `/api/v1/log` → cari "TikTok Auto-Fetch"
3. Kalau masih gagal → check msToken

---

## 📅 MAINTENANCE

**Every 3-6 bulan:**
- Monitor 403 errors di log
- Kalau banyak 403 → generate msToken baru
- Update di Vercel

**No other maintenance!** Scraper auto-adapt.

---

## 🎉 NEXT STEPS

Setelah TikTok work, kita bisa:
1. **Fix Instagram scraper** (migrate dari RapidAPI ke direct)
2. **Fix Facebook URL parser** (handle `/share/p/...` format)
3. **Auto-match video ke unit** by caption keyword

**Priority:** TikTok dulu → IG → FB

---

## 📚 DOCUMENTATION

Full docs: [`TIKTOKSCRAPER.md`](./TIKTOKSCRAPER.md)

**Files modified:**
- `/root/phonejaya/app/services/tiktok_scraper.py` (NEW)
- `/root/phonejaya/app/services/influencer_service.py` (UPDATED)
- `/root/phonejaya/TIKTOKSCRAPER.md` (NEW)
- `/root/phonejaya/SETUP_SCRAPER.md` (THIS FILE)

---

**Last updated:** 2026-07-08  
**Author:** Hermes Agent  
**Status:** READY FOR TESTING ✅