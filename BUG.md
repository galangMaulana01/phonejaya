# BUG.md v2 — Phonejaya / Jayaphone

Generated: 2026-07-20 (Full Re-Audit from Zero, Session Baru)

---

## LEGEND

| Status | Meaning |
|--------|---------|
| VERIFIED | Bug confirmed + fix verified with evidence |
| FIXED | Code changed, needs live test |
| OPEN | Bug confirmed, not yet fixed |
| SUSPECTED | Claim without evidence, needs investigation |

| Severity | Criteria |
|----------|----------|
| Critical (P0) | Data loss, security bypass, auth bypass, race condition causing wrong results |
| High (P1) | Broken feature, wrong data exposure, race condition on financial data |
| Medium (P2) | Cross-branch data leakage, missing ownership checks, code quality |
| Low (P3) | Dead code, cosmetic, minor inconsistency |

---

## PREVIOUS SESSION BUGS (001-028) — RE-VERIFIED 2026-07-20

### VERIFIED (18): 001, 002, 003, 004, 005, 006, 007, 008, 009, 010, 013, 014, 015, 016, 017, 018, 019, 020
All re-verified via grep/read against current code. Status unchanged.

### FIXED — Needs Live Test (8): 011, 012, 021, 022, 023, 024, 025, 026, 027, 028
Code changes present. Status unchanged from previous session.

---

## NEW BUGS (Session 2026-07-20)

---

## BUG-029 [SESSION 2]
- **Severity:** High (P1)
- **Repository:** Backend
- **Role:** Kurir
- **File:** app/routes/cod.py:328
- **Evidence:**
```
$ grep -n "db\.logs\|db\.log" app/routes/cod.py app/services/log_service.py
app/routes/cod.py:328:    cursor = db.logs.find(query).sort("created_at", -1).limit(limit)
app/services/log_service.py:48:        await db.log.insert_one({
```
- **Root Cause:** `kurir_log` endpoint queries `db.logs` (plural) but `write_log()` inserts into `db.log` (singular). The query always returns empty results.
- **Impact:** Kurir cannot see their activity log — feature completely broken.
- **Fix Plan:** Change `db.logs` to `db.log` on cod.py:328.
- **Regression Risk:** Low — single collection name fix.
- **Status:** OPEN

---

## BUG-030 [SESSION 2]
- **Severity:** Medium (P2)
- **Repository:** Backend
- **Role:** Kasir, Teknisi
- **File:** app/services/customer_service.py:18-22, app/routes/customer.py:13-20
- **Evidence:**
```
$ cat app/services/customer_service.py
async def list_customer(db, q: Optional[str]=None) -> List[CustomerResponse]:
    query: dict = {}
    if q: query["$or"] = [{"nama":{"$regex":q,"$options":"i"}},{"kontak":{"$regex":q,"$options":"i"}}]
    docs = await db.customers.find(query).sort("nama", 1).to_list(length=None)
    return [_fmt(d) for d in docs]
```
- **Root Cause:** `list_customer` has NO cabang filter. Any kasir/teknisi can see customers from ALL branches.
- **Impact:** Cross-branch customer data leakage. Kasir JKT can see SBY customers.
- **Fix Plan:** Add cabang parameter to list_customer, filter by user's cabang in route handler.
- **Regression Risk:** Low — adding filter, not changing existing behavior for owner.
- **Status:** OPEN

---

## BUG-031 [SESSION 2]
- **Severity:** Medium (P2)
- **Repository:** Backend
- **Role:** Kasir (auto-create during transaction)
- **File:** app/services/transaksi_service.py:137-143
- **Evidence:**
```
$ sed -n '137,143p' app/services/transaksi_service.py
            new_customer = await create_customer(db,
                __import__("app.schemas.customer", fromlist=["CustomerCreateRequest"]).CustomerCreateRequest(
                    nama=payload.customer_nama.strip(),
                    kontak=payload.customer_kontak.strip() if payload.customer_kontak else ""
                ),
                actor=kasir_name
            )
```
- **Root Cause:** CustomerCreateRequest created without `cabang` field. Schema defaults cabang to "" (empty string). Customer created during transaction has NO branch association.
- **Impact:** Auto-created customers have empty cabang, making them invisible to branch-filtered queries.
- **Fix Plan:** Pass `cabang=cabang` to the inline CustomerCreateRequest.
- **Regression Risk:** Low — adding missing field.
- **Status:** OPEN

---

## BUG-032 [SESSION 2]
- **Severity:** Medium (P2)
- **Repository:** Backend
- **Role:** Kasir, Teknisi
- **File:** app/routes/units.py:69-85
- **Evidence:**
```
$ sed -n '69,85p' app/routes/units.py
@router.get("/{unit_id}/detail")
async def unit_detail(
    unit_id: str,
    db:   AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_kasir_teknisi_or_owner),
):
    from fastapi import HTTPException
    doc = await db.units.find_one({"unit_id": unit_id})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Unit {unit_id} tidak ditemukan")
    unit = unit_service._fmt(doc)
    data = unit.model_dump()
    if user.get("role") == "teknisi":
        data.pop("harga_modal", None)
    return ok(data)
```
- **Root Cause:** `unit_detail` does NOT validate that the unit belongs to the user's cabang. Any kasir can see any unit's full detail across all branches.
- **Impact:** Cross-branch unit data exposure. Kasir JKT can view SBY unit details.
- **Fix Plan:** Add cabang check: `if user.get("role") != "owner" and doc.get("cabang") != user.get("cabang"): raise 403`.
- **Regression Risk:** Low — adding ownership check.
- **Status:** OPEN

---

## BUG-033 [SESSION 2]
- **Severity:** High (P1)
- **Repository:** Backend
- **Role:** Kasir
- **File:** app/services/transaksi_service.py:220-238
- **Evidence:**
```
$ sed -n '220,238p' app/services/transaksi_service.py
    for item in payload.items:
        sp = await db.sparepart.find_one({"sp_id": item.sp_id})
        if not sp:
            raise HTTPException(status_code=404, detail=f"Sparepart {item.sp_id} tidak ditemukan")
        if sp["stok"] < item.jumlah:
            raise HTTPException(
                status_code=400,
                detail=f"Stok {sp['nama']} tidak cukup. Tersedia: {sp['stok']}, diminta: {item.jumlah}"
            )
        if sp.get("cabang") != cabang:
            raise HTTPException(status_code=403, detail=f"Sparepart {sp['nama']} bukan milik cabangmu")
        total_jual  += sp["harga_jual"]  * item.jumlah
        total_modal += sp["harga_beli"]  * item.jumlah
        labels.append(f"{sp['nama']} x{item.jumlah}")

        await db.sparepart.update_one(
            {"sp_id": item.sp_id}, {"$set": {"stok": sp["stok"] - item.jumlah, "updated_at": datetime.now(timezone.utc)}}
        )
```
- **Root Cause:** Legacy `create_transaksi_sparepart` does read-then-write instead of atomic `find_one_and_update`. Same pattern as BUG-009 but in the legacy endpoint. Stok can go negative under concurrent transactions.
- **Impact:** Race condition — sparepart stock goes negative when two kasir sell same sparepart simultaneously.
- **Fix Plan:** Replace read-then-write with `find_one_and_update({"sp_id": ..., "stok": {"$gte": item.jumlah}}, {"$inc": {"stok": -item.jumlah}})`.
- **Regression Risk:** Low — same fix pattern as BUG-009.
- **Status:** OPEN

---

## BUG-034 [SESSION 2]
- **Severity:** Medium (P2)
- **Repository:** Backend
- **Role:** Kurir, Kasir
- **File:** app/services/cod_service.py:248-293
- **Evidence:**
```
$ sed -n '248,293p' app/services/cod_service.py
    # ── PATH 2: Existing ownership check (unchanged) ──
    doc = await db.cod_requests.find_one({"cod_id": cod_id})
    ...
    current = doc["status"]
    flow = ALL_FLOWS[doc["type"]]
    if new_status not in flow.get(current, []):
        raise HTTPException(...)
    ...
    await db.cod_requests.update_one(
        {"cod_id": cod_id}, {"$set": {
            "status": new_status,
            "status_history": status_history,
            "updated_at": now
        }}
    )
```
- **Root Cause:** PATH 2 does find_one + update_one non-atomically. Between read and write, another request could change status. Flow validation catches invalid transitions but the update itself is not conditional on current status.
- **Impact:** Status could be set to an invalid intermediate state if two requests race.
- **Fix Plan:** Use `find_one_and_update` with status filter for PATH 2 as well.
- **Regression Risk:** Low — making existing logic atomic.
- **Status:** OPEN

---

## BUG-035 [SESSION 2]
- **Severity:** Medium (P2)
- **Repository:** Backend
- **Role:** Kasir (COD approval)
- **File:** app/services/cod_service.py:494-500
- **Evidence:**
```
$ sed -n '494,500p' app/services/cod_service.py
    await db.units.insert_one(unit_doc)
    # Route to inventory or service
    unit_label = f"{unit_doc['merk']} {unit_doc['tipe']} {unit_doc['storage']}"
    await route_unit_to_inventory_or_service(
        db, unit_id, unit_label, kondisi_hp, cabang, kasir_name,
        keluhan=unit_data.get("keluhan", "")
    )
```
- **Root Cause:** Unit is created (insert_one) then routed to inventory/service. If routing fails (e.g., service ticket creation fails), the unit exists but is in wrong state (status=Tersedia but should be Service).
- **Impact:** Partial state — unit exists without proper routing.
- **Fix Plan:** Wrap in try/except, rollback unit creation on routing failure.
- **Regression Risk:** Medium — adding error handling to critical path.
- **Status:** OPEN

---

## BUG-036 [SESSION 2]
- **Severity:** High (P1)
- **Repository:** Backend
- **Role:** Kasir, Owner
- **File:** app/services/cod_service.py:402-509, app/routes/cod.py:264-275
- **Evidence:**
```
$ sed -n '264,275p' app/routes/cod.py
@router.post("/{cod_id}/approve", response_model=dict)
async def approve_beli(
    cod_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_kasir_teknisi_or_owner),
):
    kasir_name = user.get("name") or user.get("username")
    cabang = user.get("cabang")
    cod = await cod_service.approve_beli_cod(db, cod_id, kasir_name, cabang)
    return ok(cod.model_dump(), message=f"COD {cod_id} disetujui — unit masuk inventory")

$ sed -n '416,421p' app/services/cod_service.py
    doc = await db.cod_requests.find_one_and_update(
        {"cod_id": cod_id, "status": "menunggu_approval_kasir", "type": "beli"},
        ...
    )
```
- **Root Cause:** `approve_beli_cod` does NOT validate that the COD's cabang matches the approving kasir's cabang. Any kasir can approve any COD from any branch, and the unit gets created in THEIR cabang instead of the original.
- **Impact:** Cross-branch COD approval — unit created in wrong branch. Data integrity compromised.
- **Fix Plan:** Add `doc["cabang"] != cabang` check before processing, or add cabang to the find_one_and_update filter.
- **Regression Risk:** Low — adding ownership validation.
- **Status:** OPEN

---

## BUG-037 [SESSION 2]
- **Severity:** High (P1)
- **Repository:** Backend
- **Role:** Kasir, Teknisi, Owner
- **File:** app/routes/units.py:39-51, app/schemas/unit.py:46
- **Evidence:**
```
$ sed -n '46p' app/schemas/unit.py
    cabang:        str = "JYP"
$ sed -n '39,51p' app/routes/units.py
@router.post("", status_code=201)
async def create_unit(
    body: UnitCreateRequest,
    db:   AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_kasir_teknisi_or_owner),
):
    unit = await unit_service.create_unit(db, body, actor=user.get("name", user.get("username", "")))
```
- **Root Cause:** `create_unit` takes cabang from the request body (defaults to "JYP"). The route handler does NOT override body.cabang with user.get("cabang"). A kasir could inject a different cabang via the API.
- **Impact:** Kasir can create units in any branch by manipulating the cabang field in the request body.
- **Fix Plan:** Force `body.cabang = user.get("cabang")` for non-owner roles (like sparepart.py:32-33 does).
- **Regression Risk:** Low — adding authorization enforcement.
- **Status:** OPEN

---

## BUG-038 [SESSION 2]
- **Severity:** Low (P3)
- **Repository:** Backend
- **Role:** N/A (dead code)
- **File:** app/routes/owner_influencer.py
- **Evidence:**
```
$ grep "owner_influencer" app/main.py
(no output — not imported)
$ wc -l app/routes/owner_influencer.py
51 app/routes/owner_influencer.py
```
- **Root Cause:** `owner_influencer.py` (51 lines) duplicates endpoints in `influencer.py`. Not registered in main.py. Dead code.
- **Impact:** No runtime impact. Code confusion.
- **Fix Plan:** Delete file.
- **Regression Risk:** Low.
- **Status:** OPEN

---

## BUG-039 [SESSION 2]
- **Severity:** Low (P3)
- **Repository:** Frontend
- **Role:** Owner/Admin
- **File:** main.js:430
- **Evidence:**
```
$ sed -n '430p' main.js
    delete: function(publicId) { return uploadFile('/upload/image', new Blob([publicId], {type: 'application/json'})); },
```
- **Root Cause:** `upload.delete` uses POST with Blob instead of DELETE method. Backend has `DELETE /image` endpoint. This sends a POST to `/upload/image` with a Blob body, which likely hits the upload endpoint instead of delete.
- **Impact:** Image deletion may not work as intended (depends on backend routing).
- **Fix Plan:** Change to `request('DELETE', '/image?id=' + publicId)` or check backend delete route signature.
- **Regression Risk:** Low.
- **Status:** SUSPECTED (needs backend route verification)

---

## BUG-040 [SESSION 2]
- **Severity:** Medium (P2)
- **Repository:** Backend
- **Role:** Kasir (COD approval)
- **File:** app/services/cod_service.py:512-555
- **Evidence:**
```
$ sed -n '522,527p' app/services/cod_service.py
    doc = await db.cod_requests.find_one_and_update(
        {"cod_id": cod_id, "status": "menunggu_approval_kasir", "type": "beli"},
        {"$set": {"status": "ditolak", ...}},
        return_document=True
    )
```
- **Root Cause:** Same as BUG-036 — `reject_beli_cod` also does NOT validate cabang ownership. Any kasir can reject any COD from any branch.
- **Impact:** Cross-branch COD rejection.
- **Fix Plan:** Same as BUG-036 — add cabang check.
- **Regression Risk:** Low.
- **Status:** OPEN (same root cause as BUG-036)

---

## BUG-041 [SESSION 2]
- **Severity:** Medium (P2)
- **Repository:** Backend
- **Role:** Kasir, Teknisi
- **File:** app/services/sparepart.py:101-108
- **Evidence:**
```
$ sed -n '95,108p' app/services/sparepart.py
    sp = await db.sparepart.find_one({"sp_id": sp_id})
    ...
    stok_baru = sp["stok"] + payload.delta
    if stok_baru < 0:
        raise HTTPException(status_code=400, detail=f"Stok tidak cukup...")
    ...
    await db.sparepart.update_one(
        {"sp_id": sp_id}, {"$set": {"stok": stok_baru, "updated_at": now}}
    )
```
- **Root Cause:** `update_stok` does read-then-write. Two simultaneous updates could both read the same stok value, causing one update to overwrite the other.
- **Impact:** Stok could become inconsistent under concurrent admin updates.
- **Fix Plan:** Use atomic `find_one_and_update` with conditional stok check for decrements.
- **Regression Risk:** Low.
- **Status:** OPEN

---

## BUG-042 [SESSION 2]
- **Severity:** Medium (P2)
- **Repository:** Backend
- **Role:** Teknisi
- **File:** app/services/sparepart.py:124-136
- **Evidence:**
```
$ sed -n '124,136p' app/services/sparepart.py
    for item in items:
        sp = await db.sparepart.find_one({"sp_id": item["sp_id"]})
        ...
        actual_deducted = min(sp["stok"], item["jumlah"])
        stok_baru = sp["stok"] - actual_deducted
        await db.sparepart.update_one(
            {"sp_id": item["sp_id"]}, {"$set": {"stok": stok_baru, ...}}
        )
```
- **Root Cause:** `kurangi_stok_batch` does read-then-write per item. Same race condition pattern as BUG-041 but in batch context.
- **Impact:** Stok could go negative if two service completions run simultaneously.
- **Fix Plan:** Use atomic `find_one_and_update` with `$gte` check per item.
- **Regression Risk:** Low.
- **Status:** OPEN

---

## Summary

| Status | Count |
|--------|-------|
| VERIFIED (prev session) | 18 |
| FIXED — needs live test (prev) | 10 |
| OPEN (new) | 12 |
| SUSPECTED (new) | 1 |
| **Total** | **41** |

### OPEN — Critical (0): None
### OPEN — High (5): BUG-029, 033, 036, 037, 040
### OPEN — Medium (6): BUG-030, 031, 032, 034, 035, 041, 042
### OPEN — Low (1): BUG-038
### SUSPECTED (1): BUG-039

### Priority Fix Order:
1. **BUG-029** (HIGH) — kurir_log wrong collection — 1 line fix
2. **BUG-037** (HIGH) — create_unit cabang injection — 1 line fix
3. **BUG-036+040** (HIGH) — approve/reject COD no cabang check — 2 line fix
4. **BUG-033** (HIGH) — legacy sparepart transaction race — refactor to atomic
5. **BUG-032** (MEDIUM) — unit_detail no cabang check — 2 line fix
6. **BUG-030** (MEDIUM) — customer no cabang filter — 3 line fix
7. **BUG-031** (MEDIUM) — customer no cabang in transaction — 1 line fix
8. **BUG-034** (MEDIUM) — COD status update non-atomic — refactor PATH 2
9. **BUG-035** (MEDIUM) — approve_beli partial state — add try/except
10. **BUG-041+042** (MEDIUM) — sparepart stock race — refactor to atomic
11. **BUG-038** (LOW) — delete dead route file
12. **BUG-039** (SUSPECTED) — upload.delete POST vs DELETE
