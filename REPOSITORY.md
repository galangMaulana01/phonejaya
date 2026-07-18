# REPOSITORY.md — Phonejaya / Jayaphone

Generated: 2026-07-19 (Phase 1 — Repository Intelligence)

---

## 1. Project Overview

| Field | Backend (phonejaya) | Frontend (jayaphone) |
|-------|--------------------|--------------------|
| Path | `/root/phonejaya` | `/root/jayaphone` |
| Stack | FastAPI + Motor (async MongoDB) | HTML/CSS/Vanilla JS (SPA) |
| Deploy | Vercel (serverless, Mangum adapter) | Vercel (static) |
| DB | MongoDB Atlas | — |
| Python | 3.12 (Vercel) / 3.13-3.14 (local) | — |
| Files | 67 .py files, ~7100 LOC | 3 files, ~6500 LOC |
| API prefix | `/api/v1` | — |
| Domain | `jayaphone.vercel.app` / `phonejaya.vercel.app` | Same |

---

## 2. Backend Structure

```
/root/phonejaya/
├── api/index.py              # Vercel entry: Mangum(app, lifespan="off")
├── vercel.json               # maxDuration=60, PYTHON_VERSION=3.12
├── requirements.txt          # fastapi, motor, pydantic, jose, bcrypt, cloudinary, slowapi
├── .env / .env.example       # MONGO_URI, JWT_SECRET, CLOUDINARY_*, CRON_SECRET
└── app/
    ├── main.py               # create_app(), CORS, rate limiter, 15 routers
    ├── config/
    │   ├── settings.py       # pydantic-settings: MONGO_*, JWT_*, CLOUDINARY_*, CORS
    │   └── database.py       # Motor client, init_db (unique indexes)
    ├── middlewares/
    │   └── auth.py           # 9 auth guards (see RBAC table)
    ├── routes/               # 16 route files (15 registered + 1 dead)
    ├── services/             # 17 service files
    ├── schemas/              # 12 schema files
    └── utils/
        ├── security.py       # bcrypt + JWT (python-jose)
        ├── id_generator.py   # Auto-ID: unit, trx, service, video, cod, transfer
        ├── objectid.py       # ObjectId helper
        └── formatters.py     # fmt_waktu()
```

### 2.1 MongoDB Collections

| Collection | Unique Index | Used By |
|-----------|-------------|---------|
| `users` | username | auth_service, karyawan_service, cabang_service |
| `karyawan` | username | karyawan_service, cabang_service |
| `cabang` | kode | cabang_service |
| `units` | (unit_id, cabang) | unit_service, transaksi_service, transfer_stok_service |
| `service` | service_id | service_service, unit_service |
| `transaksi` | trx_id | transaksi_service |
| `sparepart` | sp_id | sparepart.py, transaksi_service |
| `influencer_videos` | video_id | influencer_service |
| `customers` | (none) | customer_service, transaksi_service |
| `cod_requests` | (none) | cod_service |
| `transfer_stok` | (none) | transfer_stok_service |
| `request_sparepart` | (none) | request_sparepart_service |
| `log` | (none) | log_service |
| `counters` | _id | id_generator (all auto-IDs) |

### 2.2 Registered Routers (main.py)

| # | Import | Prefix | Tags |
|---|--------|--------|------|
| 1 | auth | /api/v1/auth | Auth |
| 2 | units | /api/v1/units | Units |
| 3 | transaksi | /api/v1/transaksi | Transaksi |
| 4 | karyawan | /api/v1/karyawan | Karyawan |
| 5 | log | /api/v1/log | Log |
| 6 | dashboard | /api/v1/dashboard | Dashboard |
| 7 | service | /api/v1/service | Service |
| 8 | customer | /api/v1/customers | Customer |
| 9 | sparepart | /api/v1/sparepart | Sparepart |
| 10 | cabang | /api/v1/cabang | Cabang |
| 11 | request_sparepart | /api/v1/request-sparepart | Request Sparepart |
| 12 | transfer_stok | /api/v1/transfer-stok | Transfer Stok |
| 13 | influencer | /api/v1/influencer | Influencer |
| 14 | upload | /api/v1/upload | Upload |
| 15 | cod | /api/v1/cod | COD |

**DEAD ROUTE:** `owner_influencer.py` exists at `/root/phonejaya/app/routes/owner_influencer.py` but is NOT imported in `main.py`. Its 3 endpoints duplicate what `influencer.py` already provides under `/influencer/owner/*`.

---

## 3. Complete Endpoint Map

### 3.1 Auth (`/api/v1/auth`)
| Method | Path | Auth Guard | Function |
|--------|------|-----------|----------|
| POST | /login | None | login |
| GET | /me | get_current_user | me |

### 3.2 Units (`/api/v1/units`)
| Method | Path | Auth Guard | Function |
|--------|------|-----------|----------|
| GET | / | require_any | list_units |
| POST | / | require_kasir_teknisi_or_owner | create_unit |
| POST | /{unit_id}/approve-repair | require_kasir_teknisi_or_owner | approve_repair |
| GET | /{unit_id}/detail | require_any | unit_detail |

### 3.3 Transaksi (`/api/v1/transaksi`)
| Method | Path | Auth Guard | Function |
|--------|------|-----------|----------|
| GET | / | require_kepala_or_owner | list_transaksi |
| POST | / | require_kasir_teknisi_or_owner | create_transaksi |
| GET | /{trx_id}/detail | require_any | trx_detail |
| POST | /sparepart | require_kasir_teknisi_or_owner | create_sparepart_trx |

### 3.4 Karyawan (`/api/v1/karyawan`)
| Method | Path | Auth Guard | Function |
|--------|------|-----------|----------|
| GET | / | require_kepala_or_owner | list_karyawan |
| POST | / | require_kepala_or_owner | create_karyawan |
| PATCH | /{karyawan_id}/password | require_owner | reset_password |
| GET | /{karyawan_id}/stats | require_kepala_or_owner | karyawan_stats |

### 3.5 Log (`/api/v1/log`)
| Method | Path | Auth Guard | Function |
|--------|------|-----------|----------|
| GET | / | require_teknisi_or_owner | list_log |

### 3.6 Dashboard (`/api/v1/dashboard`)
| Method | Path | Auth Guard | Function |
|--------|------|-----------|----------|
| GET | /stats | require_kepala_or_owner | dashboard_stats |
| GET | /trend | require_kepala_or_owner | dashboard_trend |

### 3.7 Service (`/api/v1/service`)
| Method | Path | Auth Guard | Function |
|--------|------|-----------|----------|
| GET | / | require_any | list_service |
| GET | /pending-approval | require_kasir_teknisi_or_owner | pending_approval |
| GET | /{service_id} | require_any | get_service |
| PUT | /{service_id} | require_teknisi_or_owner | update_service |
| GET | /{service_id}/detail | require_any | service_detail |

### 3.8 Customer (`/api/v1/customers`)
| Method | Path | Auth Guard | Function |
|--------|------|-----------|----------|
| GET | / | require_kasir_teknisi_or_owner | list_customer |
| POST | / | require_kasir_teknisi_or_owner | create_customer |

### 3.9 Sparepart (`/api/v1/sparepart`)
| Method | Path | Auth Guard | Function |
|--------|------|-----------|----------|
| GET | / | require_kasir_teknisi_or_owner | list_sparepart |
| POST | / | require_kepala_or_owner | create_sparepart |
| PATCH | /{sp_id}/stok | require_kepala_or_owner | update_stok |

### 3.10 Cabang (`/api/v1/cabang`)
| Method | Path | Auth Guard | Function |
|--------|------|-----------|----------|
| GET | / | require_owner | list_cabang |
| POST | / | require_owner | create_cabang |
| PATCH | /{kode} | require_owner | update_cabang |
| POST | /{kode}/kepala | require_owner | assign_kepala |
| DELETE | /karyawan/{karyawan_id} | require_owner | pecat_karyawan |

### 3.11 Request Sparepart (`/api/v1/request-sparepart`)
| Method | Path | Auth Guard | Function |
|--------|------|-----------|----------|
| GET | / | require_kasir_teknisi_or_owner | list_requests |
| POST | / | require_kasir_teknisi_or_owner | create_request |
| PATCH | /{req_id} | require_kepala_or_owner | respond_request |

### 3.12 Transfer Stok (`/api/v1/transfer-stok`)
| Method | Path | Auth Guard | Function |
|--------|------|-----------|----------|
| GET | / | require_kepala_or_owner | list_transfers |
| POST | / | require_kepala_cabang_only | create_transfer |
| PATCH | /{transfer_id} | require_kepala_or_owner | respond_transfer |
| GET | /cabang-list | require_kepala_or_owner | cabang_list |
| GET | /notif/count | require_any | notif_count |
| GET | /notif/pending | require_kepala_or_owner | notif_pending |

### 3.13 Influencer (`/api/v1/influencer`)
| Method | Path | Auth Guard | Function |
|--------|------|-----------|----------|
| GET | /dashboard/stats | require_influencer | dashboard_stats |
| GET | /catalog | require_influencer | catalog |
| POST | /videos | require_influencer | create_video |
| GET | /videos | require_influencer | list_videos |
| GET | /log | require_influencer | influencer_log |
| GET | /profile | require_influencer | profile |
| PATCH | /social | require_influencer | update_social |
| GET | /owner/dashboard | require_owner | owner_dashboard |
| GET | /owner/videos | require_owner | owner_videos |
| GET | /owner/influencers | require_owner | owner_influencers |
| POST | /sync | require_owner | trigger_sync |
| POST | /sync/cron | (CRON_SECRET header) | cron_sync |

### 3.14 Upload (`/api/v1/upload`)
| Method | Path | Auth Guard | Function |
|--------|------|-----------|----------|
| POST | /image | require_any | upload_image |
| POST | /images | require_any | upload_images |
| DELETE | /image | require_any | delete_image |
| GET | /signature | require_any | get_signature |

### 3.15 COD (`/api/v1/cod`)
| Method | Path | Auth Guard | Function |
|--------|------|-----------|----------|
| POST | / | require_kasir_teknisi_or_owner | create_cod |
| GET | /kurir-list | require_kasir_teknisi_or_owner | kurir_list |
| GET | / | require_kasir_teknisi_or_owner | list_cod |
| GET | /{cod_id} | require_kasir_teknisi_or_owner | cod_detail |
| GET | /kurir/dashboard | require_kurir | kurir_dashboard |
| POST | /kurir/{cod_id}/accept | require_kurir | kurir_accept |
| POST | /kurir/{cod_id}/reject | require_kurir | kurir_reject |
| POST | /kurir/{cod_id}/status | require_kurir | kurir_status |
| POST | /kurir/input-stok | require_kurir | kurir_input_stok |
| GET | /kurir/log | require_kurir | kurir_log |
| GET | /kurir/monitoring | require_kepala_or_owner | kurir_monitoring |

---

## 4. RBAC Matrix

### 4.1 Auth Guards (from middlewares/auth.py)

| Guard | Allowed Roles |
|-------|-------------|
| get_current_user | Any authenticated user |
| require_owner | owner |
| require_kepala_or_owner | owner, kepala_cabang |
| require_kasir_teknisi_or_owner | owner, kepala_cabang, kasir, teknisi |
| require_teknisi_or_owner | owner, kepala_cabang, teknisi, kurir |
| require_any | Any authenticated user |
| require_kepala_cabang_only | kepala_cabang only |
| require_influencer | influencer |
| require_influencer_or_owner | owner, influencer |
| require_kurir | kurir |

### 4.2 Role → Endpoint Access Matrix

| Endpoint Group | Owner | Kepala Cabang | Kasir | Teknisi | Kurir | Influencer |
|---------------|-------|--------------|-------|---------|-------|------------|
| Auth (login/me) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Units (list) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Units (create) | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ |
| Units (approve-repair) | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ |
| Transaksi (list) | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ |
| Transaksi (create) | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ |
| Karyawan (list) | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ |
| Karyawan (create) | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ |
| Karyawan (reset pw) | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Log (list) | ✓ | ✓ | ✗ | ✓ | ✓ | ✗ |
| Dashboard | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ |
| Service (list) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Service (update) | ✓ | ✓ | ✗ | ✓ | ✓ | ✗ |
| Service (pending) | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ |
| Customer | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ |
| Sparepart (list) | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ |
| Sparepart (create/stok) | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ |
| Cabang (all) | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Request Sparepart (list/create) | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ |
| Request Sparepart (respond) | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ |
| Transfer Stok (list) | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ |
| Transfer Stok (create) | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ |
| Transfer Stok (respond) | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ |
| Transfer Stok (notif) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Influencer (own) | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ |
| Influencer (owner) | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Upload | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| COD (kasir) | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ |
| COD (kurir) | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ |
| COD (monitoring) | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ |

---

## 5. State Machines

### 5.1 Unit Status
```
[Tersedia] → Sold (transaksi)
[Tersedia] → Dalam Transfer (transfer_stok create)
[Tersedia] → Service (auto when kondisi_hp=Repair)
[Service] → Tersedia (approve_repair)
[Service] → Ditolak (service rejected)
[Dalam Transfer] → Tersedia (transfer accepted/rejected)
[Booking] → (defined but unused in current code)
```

### 5.2 Service Status
```
[Antrian] → Proses | Ditolak
[Proses] → Selesai | Ditolak
[Selesai] → Approved (via approve_repair only)
[Approved] → (terminal)
[Ditolak] → (terminal)
```

### 5.3 COD Beli Status
```
[menunggu_kurir] → diterima | ditolak
[diterima] → kurir_menuju_lokasi
[kurir_menuju_lokasi] → sudah_bertemu_penjual | ditolak
[sudah_bertemu_penjual] → input_stok | ditolak
[input_stok] → selesai
[selesai] → (terminal)
[ditolak] → (terminal)
```

### 5.4 COD Jual Status
```
[menunggu_kurir] → diterima | ditolak
[diterima] → barang_akan_dijemput
[barang_akan_dijemput] → barang_sudah_diambil
[barang_sudah_diambil] → kurir_sedang_transaksi
[kurir_sedang_transaksi] → transaksi_berhasil | gagal
[transaksi_berhasil] → (terminal)
[gagal] → (terminal)
[ditolak] → (terminal)
```

### 5.5 Transfer Stok Status
```
[Pending] → Diterima | Ditolak
[Diterima] → (terminal, units reassigned)
[Ditolak] → (terminal, units restored)
```

### 5.6 Request Sparepart Status
```
[Pending] → Diterima | Ditolak
```

---

## 6. Frontend Structure

```
/root/jayaphone/
├── index.html    (5941 lines — SPA with all pages inline)
├── main.js       (432 lines — API calls, auth, routing)
└── svg.js        (150 lines — SVG icon library)
```

### 6.1 Frontend Pages/Tabs (from index.html)
- Login page
- Dashboard (Owner/Kepala Cabang)
- Units (list, input, detail)
- Transaksi (list, create)
- Service (list, detail, update)
- Sparepart (list, create, stok update)
- Karyawan (list, create, reset password)
- Customer (list, create)
- Cabang (list, create, assign kepala)
- Transfer Stok (list, create, respond, notifications)
- Influencer Dashboard (own stats, catalog, videos)
- Influencer Owner Monitor (owner view)
- COD (Kasir: create, list; Kurir: dashboard, accept/reject/status, input stok, log)
- Kurir Monitoring (Owner/KC view)
- Upload (image upload to Cloudinary)
- Log (activity log)
- Settings/Profile

### 6.2 Frontend→Backend API Calls
(Detailed in main.js — all use `/api/v1` prefix with configurable BASE_URL)

---

## 7. Key Patterns

### 7.1 Response Format
All endpoints return: `{"success": bool, "message": str, "data": any}`
(from `app/schemas/common.py`)

### 7.2 Error Handling
- HTTPException for business logic errors
- Global exception handler returns 500 with generic message
- Rate limiting: 100/minute via slowapi

### 7.3 Security
- JWT auth with 7-day expiry
- bcrypt password hashing
- CORS whitelisted origins
- Log injection sanitization
- Cloudinary signed uploads

---

## 8. Known Issues (from Phase 1 scan)

See BUG.md for full details. Summary of findings so far:
1. **CRITICAL: Expired JWT passes auth** — `decode_token()` returns payload with `_expired=True` but `get_current_user` never checks it
2. **HIGH: Dead import in request_sparepart_service.py** — imports from non-existent `app.services.sparepart_service` (should be `sparepart`)
3. **MEDIUM: Dead route file** — `owner_influencer.py` not registered in main.py
4. **MEDIUM: No unique index on cod_requests, transfer_stok, request_sparepart, customers**
5. **LOW: Duplicate lru_cache import in settings.py**
