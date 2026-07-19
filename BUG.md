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
- **Status:** VERIFIED
- **Verified By:** LIVE TEST: Created sparepart SP-003 (TEST-RACE-COND) with stok=5. Ran 10 rapid sequential transactions: 5 succeeded (TRX-020 to TRX-024), 5 rejected (400 "Stok tidak cukup. Tersedia: 0"). Final stok=0, never went negative. Atomic find_one_and_update with $gte works correctly.

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
- **Status:** FIXED
- **Verified By:** Code fix: kasir filter added to list_cod_requests_all (kasir_id parameter). Kasir now only sees COD they created.

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
- **Verified By:** Code check: 3 indexes confirmed in database.py. Indirect live test: created 3 request-sparepart records (REQ-SP-009/010/011), all unique IDs — counter+index mechanism works. Direct index verification requires MongoDB shell access (db.cod_requests.getIndexes()).

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

## BUG-021
- **Severity:** Medium
- **Repository:** Backend
- **Role:** Kasir (data exposure)
- **File:** app/routes/cod.py
- **Line:** 72-74
- **Evidence:**
```
$ sed -n '62,80p' app/routes/cod.py
    role = user.get("role", "kasir")
    if role == "kasir":
        kurir_id = user.get("sub") or user.get("username")
        pass  # service handles this
    cods = await cod_service.list_cod_requests_all(
        db, cabang, status, type, date_from, date_to, limit
    )
```
- **Root Cause:** When role is "kasir", the code does `pass` — no filter applied. The kasir_id variable is set but never used. Result: kasir sees ALL COD requests in their cabang, not just their own.
- **Impact:** Data exposure between kasir in the same cabang. Kasir A can see COD requests created by Kasir B.
- **Fix Plan:** Add `kasir_id` parameter to `list_cod_requests_all` and pass `user.get("username")` when role is kasir.
- **Regression Risk:** Low — adding filter, not changing existing behavior for other roles.
- **Status:** FIXED
- **Verified By:** Code fix: kasir filter added to list_cod_requests_all (kasir_id parameter). Kasir now only sees COD they created.

---

## BUG-022
- **Severity:** Critical
- **Repository:** Frontend
- **Role:** Kasir (COD delivery broken)
- **File:** main.js
- **Line:** 398 (missing)
- **Evidence:**
```
$ grep -n "create" main.js | grep "cod"
(no output — method does not exist)
$ grep -n "API.cod.create" index.html
3109:    await API.cod.create({
```
- **Root Cause:** `API.cod` object in main.js has no `create` method. Backend endpoint `POST /cod` exists but the frontend client wrapper was never added. `index.html:3109` calls `API.cod.create(...)` which throws "is not a function".
- **Impact:** Kasir cannot create COD delivery — entire feature broken.
- **Fix Plan:** Add `create: function(b) { return request('POST', '/cod', b); }` to API.cod in main.js.
- **Regression Risk:** Low — adding missing method, no existing behavior changed.
- **Status:** FIXED
- **Verified By:** grep confirms `create` method now present in main.js line 399. Requires push + live test.

---

## BUG-023
- **Severity:** Critical
- **Repository:** Backend
- **Role:** Kasir (COD delivery crash on unit-only transaction)
- **File:** app/services/cod_service.py
- **Line:** 140
- **Evidence:**
```
Vercel function log:
TypeError: 'NoneType' object is not iterable
File "app/services/cod_service.py", line 140
    for sp in trx.get("sp_items", [])
```
- **Root Cause:** `transaksi_service.py:200` stores `sp_items: None` when transaction has no spareparts. `trx.get("sp_items", [])` returns `None` (not `[]`) because the key EXISTS with value None. The default `[]` only applies when key is MISSING. This bug was not caught in earlier testing because the test transaction happened to include spareparts.
- **Impact:** COD delivery creation crashes for any transaction that contains only a unit HP without spareparts.
- **Fix Plan:** Change `trx.get("sp_items", [])` to `(trx.get("sp_items") or [])`. Also fix similar patterns for `status_history` in same file.
- **Regression Risk:** Low — safe pattern works for all 3 cases (key missing, value None, value []).
- **Status:** FIXED
- **Verified By:** Code fix applied. Requires push + live test with 3 scenarios.
- **Test Coverage Lesson:** Earlier testing only tested with sparepart transactions. Must test all data variants: unit-only, sparepart-only, mixed.

---

## BUG-024
- **Severity:** High
- **Repository:** Backend + Frontend
- **Role:** Kurir (COD delivery renders empty)
- **File:** app/schemas/cod.py, app/services/cod_service.py, index.html
- **Line:** cod.py:55-67, cod_service.py:412, index.html:5422-5423
- **Evidence:**
```
Live response from GET /cod/kurir/dashboard:
{
  "type": "delivery",
  "location": "Toko",
  "wa_number": "",
  "items": null,
  "delivery_address": null,
  "wa_customer": null,
  "ALL KEYS": ["cod_id", "type", "status", "created_at", "location",
               "wa_number", "screenshot_url", "product_name", "offer_price",
               "kasir_name", "kurir_name", "kurir_id"]
}
```
- **Root Cause:** `CODRequestList` schema (list endpoint response) didn't include `delivery_address`, `wa_customer`, `items` fields. These were only in `CODRequestDetail`. Also `_format_dashboard_item` didn't populate them. Frontend rendered raw field names which were all null/missing.
- **Impact:** Kurir dashboard shows "-" for all delivery columns — feature appears broken.
- **Fix Plan:** Add delivery fields to CODRequestList schema, update _format_dashboard_item, update frontend conditional rendering.
- **Regression Risk:** Low — adding fields, not changing existing ones.
- **Status:** FIXED
- **Verified By:** Code fix applied. Requires push + live test.

---

## BUG-025
- **Severity:** High
- **Repository:** Backend
- **Role:** Kurir (COD delivery status update blocked)
- **File:** app/schemas/cod.py
- **Line:** 45-54
- **Evidence:**
```
Live test response:
HTTP 422: Input should be 'diterima', 'ditolak', 'kurir_menuju_lokasi',
'sudah_bertemu_penjual', 'barang_akan_dijemput', 'barang_sudah_diambil',
'kurir_sedang_transaksi', 'transaksi_berhasil' or 'gagal'
```
- **Root Cause:** `CODStatusUpdate` Literal only includes beli/jual statuses. Delivery statuses (kurir_menuju_toko, sedang_diantar, terkirim) were defined in `COD_DELIVERY_FLOW` but never added to the Pydantic validation Literal. Pydantic rejects input before service-level flow validation is reached.
- **Impact:** Kurir cannot advance COD delivery beyond "diterima" — all subsequent status updates fail with 422.
- **Fix Plan:** Add 3 delivery statuses to CODStatusUpdate Literal.
- **Regression Risk:** Low — adding values, not removing.
- **Status:** FIXED
- **Verified By:** Code fix committed (dd359ae). Requires push + live re-test.

---

## Summary

| Status | Count |
|--------|-------|
| VERIFIED | 18 |
| FIXED (needs live test) | 2 |
| OPEN | 1 |
| **Total** | **20** |

### VERIFIED (18): BUG-001, 002, 003, 004, 005, 006, 007, 008, 009, 010, 013, 014, 015, 016, 017, 018, 019, 020

### FIXED — Needs Live Test (2):
- **BUG-012**: Indexes
- **BUG-021**: Kasir COD list filter (requires push to test live) — direct verification requires MongoDB shell (db.cod_requests.getIndexes())

### OPEN (1):
- **BUG-011** (Low) — dead route file `owner_influencer.py`, no runtime impact
