# LIVE_VERIFICATION.md — Phonejaya/Jayaphone

Generated: 2026-07-19 (Live production verification)

Backend: https://phonejaya.vercel.app
Frontend: https://jayaphone.vercel.app

---

## 1. Login Verification (All 6 Roles)

| Role | Username | Status | User Name |
|------|----------|--------|-----------|
| Owner | owner | 200 OK | Budi Santoso |
| Kepala Cabang | empruy | 200 OK | Mas empruy |
| Kasir | anjay | 200 OK | anjay |
| Influencer | freya | 200 OK | freya |
| Kurir | cok | 200 OK | cok |
| Teknisi | anjing | 200 OK | anjing |

---

## 2. FIXED Bug Verification (5 bugs)

### BUG-002: Transfer Stok Accept
- **Test:** KC (empruy/BDG) created transfer TRF-005 (BDG-IP-BN-026 → JKT), Owner accepted
- **Result:** 201 create, 200 accept. Unit moved: BDG-IP-BN-026 → JKT-IP-BN-002
- **Status:** VERIFIED

### BUG-004: Kurir Unit ID Format
- **Test:** Kurir POST /cod/kurir/input-stok with kat_kode="AI"
- **Result:** 201 Created. Unit ID: BDG-AI-BN-009 (correct format)
- **Status:** VERIFIED

### BUG-005: Kurir Unit Schema Consistency
- **Test:** GET /units/BDG-AI-BN-009/detail
- **Result:** 200 OK. All 13 standard fields present (imei2, tipe_sim, keamanan, speaker, lcd, battery_health, locked, garansi_toko, kategori, harga_modal, harga_jual, battery, kondisi_hp)
- **Status:** VERIFIED

### BUG-009: Atomic Sparepart Stok
- **Test:** No sparepart data in test DB (kasir view shows 0 spareparts)
- **Status:** FIXED (code verified, needs data to test transaction path)

### BUG-012: Unique Indexes
- **Test:** Requires MongoDB shell access
- **Status:** FIXED (code verified in database.py)

---

## 3. RBAC Smoke Test

| Role | Endpoint | Expected | Actual | Result |
|------|----------|----------|--------|--------|
| influencer | GET /dashboard/stats | 403 | 403 | PASS |
| kurir | GET /cabang | 403 | 403 | PASS |
| influencer | GET /transaksi | 403 | 403 | PASS |
| kurir | GET /karyawan | 403 | 403 | PASS |
| owner | GET /auth/me | 200 | 200 | PASS |
| kurir | GET /cod/kurir/dashboard | 200 | 200 | PASS |
| influencer | GET /influencer/dashboard/stats | 200 | 200 | PASS |
| teknisi | GET /service | 200 | 200 | PASS |
| kasir | GET /sparepart | 200 | 200 | PASS |
| influencer | GET /transaksi/{id}/detail | 403 | 403 | PASS |
| kurir | GET /transaksi/{id}/detail | 403 | 403 | PASS |
| owner | GET /transaksi/{id}/detail | 200 | 200 | PASS |
| influencer | GET /units | 403 | 403 | PASS |
| kurir | GET /units | 403 | 403 | PASS |
| kasir | GET /units | 200 | 200 | PASS |

**Result: 15/15 PASS**

---

## 4. Live-Only Checks

### CORS
- Origin: https://jayaphone.vercel.app
- `access-control-allow-origin: https://jayaphone.vercel.app` ✓
- `access-control-allow-credentials: true` ✓
- Methods: DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT ✓
- Headers: Content-Type, Authorization ✓

### Health Check
```json
{"status":"ok","app":"JAYAPONA","version":"2.0.0"}
```

### Cold Start
- First request after idle: 0.4s (acceptable for Vercel serverless)

### Auth Expiry (BUG-001)
- Login with non-existent user: 401 "Username atau password salah" (not 500)
- Confirms null check fix works in production
- Expired token test: Requires waiting 7 days (cannot test now)

### Environment Variables
- All endpoints return proper JSON (no 500 from missing config)
- MongoDB connection works
- Cloudinary configured (image upload URLs returned in unit data)

---

## 5. Summary

| Category | Result |
|----------|--------|
| Login (6 roles) | 6/6 PASS |
| BUG-002 Transfer accept | VERIFIED |
| BUG-004 Kurir unit ID | VERIFIED |
| BUG-005 Kurir unit schema | VERIFIED |
| BUG-009 Atomic stok | FIXED (no data) |
| BUG-012 Indexes | FIXED (needs DB shell) |
| RBAC smoke test | 15/15 PASS |
| CORS | PASS |
| Health | PASS |
| Cold start | 0.4s PASS |
| Auth expiry | 401 PASS (non-existent user) |
