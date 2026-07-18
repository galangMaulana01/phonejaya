# BUG.md — Phonejaya / Jayaphone

Generated: 2026-07-19 (Phase 2 — Backend Deep Audit, updated through Phase 10)

---

## BUG-001
- **Severity:** Critical
- **Repository:** Backend
- **Role:** All authenticated users
- **File:** app/utils/security.py
- **Line:** 36-50
- **Evidence:**
```
$ grep -n "_expired" app/utils/security.py app/middlewares/auth.py
app/utils/security.py:45:            payload["_expired"] = True
app/middlewares/auth.py:12:    if payload.get("_expired"):
```
- **Root Cause:** `decode_token()` returns the JWT payload even when the token is expired, setting `_expired=True`. But `get_current_user()` in auth middleware NEVER checks this flag.
- **Impact:** Any expired JWT (7+ days old) still grants full access.
- **Fix Plan:** In `get_current_user()`, check `if payload.get("_expired"): raise HTTPException(401)`.
- **Regression Risk:** Low
- **Status:** VERIFIED
- **Verified By:** python3 test: create_access_token(expires_delta=timedelta(seconds=-10)), decode_token returns _expired=True, get_current_user raises HTTPException 401 "Token expired".

---

## BUG-002
- **Severity:** Critical
- **Repository:** Backend
- **Role:** Kepala Cabang (transfer receiver)
- **File:** app/services/transfer_stok_service.py
- **Line:** 285
- **Evidence:**
```
$ grep -n "Dalam Transfer" app/services/transfer_stok_service.py
285:        if unit.get("status") != "Dalam Transfer":
```
- **Root Cause:** `_proses_terima()` checked `status != "Tersedia"` but units are in "Dalam Transfer" status. Accept always failed.
- **Impact:** No transfer between branches could ever complete.
- **Fix Plan:** Change check to `status != "Dalam Transfer"`.
- **Regression Risk:** Low
- **Status:** VERIFIED
- **Verified By:** LIVE TEST: KC created TRF-005 (BDG→JKT, unit BDG-IP-BN-026). Owner accepted. Response: unit_id_baru=JKT-IP-BN-002, status=Diterima. Transfer acceptance works correctly.

---

## BUG-003
- **Severity:** High
- **Repository:** Backend
- **Role:** Kepala Cabang (sparepart request)
- **File:** app/services/request_sparepart_service.py
- **Line:** 70
- **Evidence:**
```
$ grep "from app.services.sparepart" app/services/request_sparepart_service.py
70:        from app.services.sparepart import create_sparepart
```
- **Root Cause:** Import from non-existent `app.services.sparepart_service`. Fixed to `app.services.sparepart`.
- **Impact:** Server crash (ImportError) when accepting "item_baru" sparepart requests.
- **Fix Plan:** Correct import path.
- **Regression Risk:** Low
- **Status:** VERIFIED
- **Verified By:** grep confirms correct import path. `from app.services.sparepart_service import` no longer present.

---

## BUG-004
- **Severity:** High
- **Repository:** Backend
- **Role:** Kurir
- **File:** app/routes/cod.py
- **Line:** 185
- **Evidence:**
```
$ sed -n '185,190p' app/routes/cod.py
    kat_kode = payload.get("kat_kode", "AI")
    kondisi_kode = payload.get("kondisi_kode", "BN")
    kondisi_hp = payload.get("kondisi_hp", "Mulus")
    unit_id = await next_unit_id(db, kat_kode, kondisi_kode, cabang)
```
- **Root Cause:** Used `merk` as `kat_kode`, generating wrong unit_ids like "JYP-Samsung-BN-001".
- **Impact:** Broken unit ID format, counter fragmentation.
- **Fix Plan:** Use proper kat_kode/kondisi_kode with defaults.
- **Regression Risk:** Medium
- **Status:** VERIFIED
- **Verified By:** LIVE TEST: Kurir POST /cod/kurir/input-stok with kat_kode="AI" returned 201. Unit ID: BDG-AI-BN-009 (correct CABANG-KAT-KONDISI-SEQ format).

---

## BUG-005
- **Severity:** High
- **Repository:** Backend
- **Role:** Kurir
- **File:** app/routes/cod.py
- **Line:** 188-210
- **Evidence:**
```
$ grep "imei2\|tipe_sim\|keamanan\|speaker\|lcd\|battery_health\|locked\|garansi_toko\|kategori" app/routes/cod.py | head -10
        "imei2": "-",
        "tipe_sim": "Single SIM",
        "keamanan": "Tidak Ada",
        "speaker": "Normal",
        "lcd": "Original",
        "battery_health": 0,
        "locked": False,
        "garansi_toko": 7,
        "kategori": resolve_kategori(kat_kode),
```
- **Root Cause:** Kurir unit doc had different field names (baterai, grade, harga_beli) than standard units.
- **Impact:** KeyError when formatting kurir-created units.
- **Fix Plan:** Align field names with standard unit schema.
- **Regression Risk:** Medium
- **Status:** VERIFIED
- **Verified By:** LIVE TEST: GET /units/BDG-AI-BN-009/detail returned 200. All 13 standard fields present (imei2, tipe_sim, keamanan, speaker, lcd, battery_health, locked, garansi_toko, kategori, harga_modal=0, harga_jual=0, battery, kondisi_hp=Mulus).

---

## BUG-006
- **Severity:** Medium
- **Repository:** Backend
- **Role:** Kurir
- **File:** app/routes/log.py
- **Line:** 31
- **Evidence:**
```
$ grep 'role.*kurir' app/routes/log.py
31:    elif user.get("role") == "kurir":
32:        query["user"] = user.get("name", user.get("username", ""))
```
- **Root Cause:** Kurir had no filter in log query, seeing ALL logs from ALL branches.
- **Impact:** Data leakage — kurir could view all activity logs.
- **Fix Plan:** Add kurir filter to own logs only.
- **Regression Risk:** Low
- **Status:** VERIFIED
- **Verified By:** grep confirms kurir role filter at line 31, filtering by own name/username.

---

## BUG-007
- **Severity:** Medium
- **Repository:** Backend
- **Role:** Teknisi
- **File:** app/routes/units.py
- **Line:** 61-63
- **Evidence:**
```
$ sed -n '61,63p' app/routes/units.py
    if user.get("role") == "teknisi":
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Teknisi tidak bisa approve repair")
```
- **Root Cause:** `approve_repair` allowed Teknisi via `require_kasir_teknisi_or_owner`.
- **Impact:** Teknisi could set harga_jual on repaired units.
- **Fix Plan:** Add role check to block teknisi.
- **Regression Risk:** Low
- **Status:** VERIFIED
- **Verified By:** grep confirms teknisi role check in approve_repair function, returns 403.

---

## BUG-008
- **Severity:** Medium
- **Repository:** Backend
- **Role:** All (Customer data)
- **File:** app/services/customer_service.py
- **Line:** 28
- **Evidence:**
```
$ grep "cabang" app/services/customer_service.py
28:        "cabang": payload.cabang,
```
- **Root Cause:** `create_customer` did not store `cabang` in customer document.
- **Impact:** Customers had no branch association.
- **Fix Plan:** Add cabang field to document.
- **Regression Risk:** Low
- **Status:** VERIFIED
- **Verified By:** grep confirms "cabang": payload.cabang at line 28 in create_customer function.

---

## BUG-009
- **Severity:** Medium
- **Repository:** Backend
- **Role:** Kasir (Transaksi)
- **File:** app/services/transaksi_service.py
- **Line:** 103-108
- **Evidence:**
```
$ grep -A3 "find_one_and_update" app/services/transaksi_service.py | head -5
            result = await db.sparepart.find_one_and_update(
                {"sp_id": item.sp_id, "stok": {"$gte": item.jumlah}},
                {"$inc": {"stok": -item.jumlah}, "$set": {"updated_at": datetime.now(timezone.utc)}},
                return_document=False,
            )
```
- **Root Cause:** Sparepart stok check and update were NOT atomic.
- **Impact:** Stok could go negative under concurrent transactions.
- **Fix Plan:** Use `find_one_and_update` with atomic check-and-decrement.
- **Regression Risk:** Low
- **Status:** FIXED
- **Verified By:** Code check: atomic find_one_and_update with $gte confirmed. Requires manual test: send concurrent POST /transaksi requests for same sparepart, verify stok never goes below 0.

---

## BUG-010
- **Severity:** Low
- **Repository:** Backend
- **Role:** N/A (code quality)
- **File:** app/config/settings.py
- **Line:** 2
- **Evidence:**
```
$ grep -c "from functools import lru_cache" app/config/settings.py
1
```
- **Root Cause:** Duplicate `lru_cache` import (was 2, now 1).
- **Impact:** Code cleanliness only.
- **Fix Plan:** Remove duplicate.
- **Regression Risk:** Low
- **Status:** VERIFIED
- **Verified By:** grep -c returns 1 (was 2 before fix).

---

## BUG-011
- **Severity:** Low
- **Repository:** Backend
- **Role:** N/A (dead code)
- **File:** app/routes/owner_influencer.py
- **Line:** 1-51
- **Evidence:**
```
$ grep "owner_influencer" app/main.py
(no output — not imported)
```
- **Root Cause:** `owner_influencer.py` duplicates endpoints in `influencer.py`. Not registered.
- **Impact:** Dead code. No runtime impact.
- **Fix Plan:** Delete file.
- **Regression Risk:** Low
- **Status:** OPEN
- **Verified By:** —

---

## BUG-012
- **Severity:** Medium
- **Repository:** Backend
- **Role:** All (data integrity)
- **File:** app/config/database.py
- **Line:** 80-88
- **Evidence:**
```
$ grep "create_index" app/config/database.py | grep -E "cod_id|transfer_id|req_id"
    await db.cod_requests.create_index("cod_id", unique=True)
    await db.transfer_stok.create_index("transfer_id", unique=True)
    await db.request_sparepart.create_index("req_id", unique=True)
```
- **Root Cause:** Missing unique indexes on cod_requests, transfer_stok, request_sparepart.
- **Impact:** Duplicate records under concurrent writes.
- **Fix Plan:** Add unique indexes.
- **Regression Risk:** Low
- **Status:** FIXED
- **Verified By:** Code check: 3 indexes confirmed in database.py. Requires manual test: verify indexes exist after app startup via `db.cod_requests.getIndexes()`.

---

## BUG-013
- **Severity:** Medium
- **Repository:** Backend
- **Role:** Owner
- **File:** app/services/cloudinary_service.py
- **Line:** 133
- **Evidence:**
```
$ grep "utcnow\|datetime.now(timezone.utc)" app/services/cloudinary_service.py
    timestamp = int(datetime.now(timezone.utc).timestamp())
```
- **Root Cause:** Used deprecated `datetime.utcnow()`.
- **Impact:** Potential timestamp issues.
- **Fix Plan:** Replace with `datetime.now(timezone.utc)`.
- **Regression Risk:** Low
- **Status:** VERIFIED
- **Verified By:** grep confirms utcnow() removed (0 matches), datetime.now(timezone.utc) present.

---

## BUG-014
- **Severity:** High
- **Repository:** Backend
- **Role:** Influencer, Kurir (data leakage)
- **File:** app/routes/transaksi.py, app/routes/units.py
- **Line:** transaksi.py:46, units.py:28, units.py:73
- **Evidence:**
```
$ grep -n "Depends(require_" app/routes/transaksi.py app/routes/units.py
app/routes/transaksi.py:31:    user: dict = Depends(require_kasir_teknisi_or_owner),
app/routes/transaksi.py:46:    user: dict = Depends(require_kasir_teknisi_or_owner),
app/routes/transaksi.py:66:    user: dict = Depends(require_kasir_teknisi_or_owner),
app/routes/units.py:28:    user:   dict = Depends(require_kasir_teknisi_or_owner),
app/routes/units.py:43:    user: dict = Depends(require_kasir_teknisi_or_owner),
app/routes/units.py:59:    user:    dict = Depends(require_kasir_teknisi_or_owner),
app/routes/units.py:73:    user: dict = Depends(require_kasir_teknisi_or_owner),
```
- **Root Cause:** Transaction detail and unit list/detail used `require_any`, exposing harga_modal/profit.
- **Impact:** Financial data visible to influencer/kurir.
- **Fix Plan:** Change to `require_kasir_teknisi_or_owner`.
- **Regression Risk:** Low
- **Status:** VERIFIED
- **Verified By:** grep confirms all endpoints use require_kasir_teknisi_or_owner. require_any only in unused import.

---

## BUG-015
- **Severity:** High
- **Repository:** Backend
- **Role:** All (login crash)
- **File:** app/services/auth_service.py
- **Line:** 10-17
- **Evidence:**
```
$ sed -n '10,17p' app/services/auth_service.py
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Username atau password salah",
        )

    stored_hash = user.get("password_hash") or user.get("password", "")
```
- **Root Cause:** `user.get()` called before checking if user is None.
- **Impact:** Login returns 500 instead of 401 for non-existent users.
- **Fix Plan:** Move null check before .get().
- **Regression Risk:** Low
- **Status:** VERIFIED
- **Verified By:** Code check: 'if not user:' at line 10, 'user.get("password_hash")' at line 17. Null check correctly precedes .get().

---

## BUG-016
- **Severity:** Medium
- **Repository:** Frontend
- **Role:** All (debug console)
- **File:** index.html
- **Line:** 15-16
- **Evidence:**
```
$ grep "eruda" index.html
<!-- <script src="https://cdn.jsdelivr.net/npm/eruda"></script> -->
<!-- <script>eruda.init();</script> -->
```
- **Root Cause:** Eruda debug console loaded in production.
- **Impact:** Security risk — users can inspect/modify app state.
- **Fix Plan:** Comment out Eruda script tags.
- **Regression Risk:** Low
- **Status:** VERIFIED
- **Verified By:** grep confirms both lines commented out with '<!-- ... -->'.

---

## BUG-017
- **Severity:** Medium
- **Repository:** Frontend
- **Role:** All (XSS via toast)
- **File:** index.html
- **Line:** 664
- **Evidence:**
```
$ grep "DOMPurify.sanitize(msg)" index.html
el.innerHTML = `${icons[type]||icons.info}<span>${DOMPurify.sanitize(msg)}</span>`;
```
- **Root Cause:** Toast messages used unsanitized msg in innerHTML.
- **Impact:** Potential XSS via error messages.
- **Fix Plan:** Use DOMPurify.sanitize(msg).
- **Regression Risk:** Low
- **Status:** VERIFIED
- **Verified By:** grep confirms DOMPurify.sanitize(msg) used in showToast innerHTML.

---

## BUG-018
- **Severity:** Medium
- **Repository:** Frontend
- **Role:** All (notification data loss)
- **File:** index.html
- **Line:** 5633
- **Evidence:**
```
$ grep "_items.*localStorage\|_items.*JSON.parse" index.html
_items: JSON.parse(localStorage.getItem('jyp_notif') || '[]'),
```
- **Root Cause:** NOTIF._items never loaded from localStorage on startup.
- **Impact:** Notifications lost on page reload.
- **Fix Plan:** Add initialization from localStorage.
- **Regression Risk:** Low
- **Status:** VERIFIED
- **Verified By:** grep confirms _items initialized with JSON.parse(localStorage.getItem('jyp_notif')).

---

## BUG-019
- **Severity:** Medium
- **Repository:** Frontend
- **Role:** Kurir (implicit global)
- **File:** index.html
- **Line:** 5470
- **Evidence:**
```
$ grep -c "event.target" index.html
0
```
- **Root Cause:** `event` used as implicit global without parameter.
- **Impact:** Button state may not update correctly.
- **Fix Plan:** Replace with document.querySelector.
- **Regression Risk:** Low
- **Status:** VERIFIED
- **Verified By:** grep -c returns 0 matches. Replaced with document.querySelector.

---

## BUG-020
- **Severity:** Low
- **Repository:** Frontend
- **Role:** Developer (debug output)
- **File:** index.html
- **Line:** 4844-4845
- **Evidence:**
```
$ grep -c "console.log" index.html
0
```
- **Root Cause:** Debug console.log left in production.
- **Impact:** Leaks API response to browser console.
- **Fix Plan:** Remove console.log lines.
- **Regression Risk:** Low
- **Status:** VERIFIED
- **Verified By:** grep -c returns 0 matches. All console.log removed.

---

## Summary

| Status | Count |
|--------|-------|
| VERIFIED | 17 |
| FIXED (needs manual test) | 2 |
| OPEN | 1 |
| **Total** | **20** |

### VERIFIED (17): BUG-001, 002, 003, 004, 005, 006, 007, 008, 010, 013, 014, 015, 016, 017, 018, 019, 020

### FIXED — Requires Manual Test (2):
- **BUG-009**: Atomic stok — concurrent transactions on same sparepart, verify stok >= 0
- **BUG-012**: Indexes — verify indexes exist after MongoDB startup

### OPEN (1):
- **BUG-011** (Low) — dead route file `owner_influencer.py`, no runtime impact
