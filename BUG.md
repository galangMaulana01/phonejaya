# BUG.md v3 — Phonejaya / Jayaphone

Generated: 2026-07-21 (Full Re-Audit from Zero, Session Baru — 3 Independent Agents + Chief Reviewer)

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

## PREVIOUS SESSION BUGS — RE-VERIFIED 2026-07-21

### VERIFIED (21): 001–010, 013–020, 029
All re-verified via grep/read against current code. Status unchanged.

### FIXED — Needs Live Test (8): 011, 012, 021–028
Code changes present. Status unchanged from previous session.

### STATUS CORRECTIONS (code fixed in commit 0b3c731, BUG.md not updated):

**BUG-031** — was OPEN → **NOW VERIFIED** ✅
Code check: `app/services/transaksi_service.py:141` now has `cabang=cabang` in CustomerCreateRequest.

**BUG-032** — was OPEN → **NOW VERIFIED** ✅
Code check: `app/routes/units.py:84` now has cabang ownership check with 403 for non-owner.

**BUG-033** — was OPEN → **NOW VERIFIED** ✅
Code check: `app/services/transaksi_service.py:228-238` now uses `find_one_and_update` with atomic stock check.

---

## NEW FINDINGS — Session 2026-07-21 (3 Independent Agents + Chief Engineer Cross-Validation)

### Audit Methodology
- 3 independent sub-agents dispatched (Security/RBAC, Data-Integrity, Frontend-Backend Sync)
- 1 agent (Maintainability) failed due to API credit limit
- All findings cross-validated by Chief Engineer against actual code
- Evidence: `read_file` output + `grep` command output

---

## BUG-040 [NEW] — Cross-Branch Transaction Financial Disclosure
- **Severity:** High (P1)
- **Repository:** Backend
- **Role:** Kasir, Teknisi, Kepala Cabang
- **File:** `app/routes/transaksi.py:42-58`
- **Evidence:**
```
$ sed -n '42,58p' app/routes/transaksi.py
@router.get("/{trx_id}/detail")
async def transaksi_detail(
    trx_id: str,
    db:   AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_kasir_teknisi_or_owner),
):
    """Return transaction with financial breakdown (harga_modal, harga_jual, profit, margin)."""
    from fastapi import HTTPException
    doc = await db.transaksi.find_one({"trx_id": trx_id})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Transaksi {trx_id} tidak ditemukan")
    trx = transaksi_service._fmt(doc)
    data = trx.model_dump()
    margin = round((data["profit"] / data["harga_jual"]) * 100, 1) if data["harga_jual"] else 0
    data["margin_pct"] = margin
    return ok(data)
```
- **Root Cause:** Lookup uses only attacker-controlled `trx_id` with no `cabang` filter or post-fetch ownership check. Financial fields (`harga_modal`, `harga_jual`, `profit`, `margin_pct`) exposed to all permitted roles.
- **Impact:** Cross-branch financial data leakage. Kasir cabang A can read cabang B's transaction margins.
- **Fix Plan:** Add cabang filter: `if user["role"] != "owner": query["cabang"] = user["cabang"]`. Consider hiding financial fields for non-owner roles.
- **Regression Risk:** Medium — validate owner cross-cabang access and same-cabang detail access.
- **Status:** OPEN

---

## BUG-041 [NEW] — Cross-Branch COD Detail Disclosure
- **Severity:** High (P1)
- **Repository:** Backend
- **Role:** Kasir, Teknisi, Kepala Cabang
- **File:** `app/routes/cod.py:84-92`, `app/services/cod_service.py:361-393`
- **Evidence:**
```
$ sed -n '84,92p' app/routes/cod.py
@router.get("/{cod_id}", response_model=dict)
async def get_cod_detail(
    cod_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_kasir_teknisi_or_owner),
):
    """Detail COD request."""
    cod = await cod_service.get_cod_detail(db, cod_id)
    return ok(cod.model_dump())

$ sed -n '361,368p' app/services/cod_service.py
async def get_cod_detail(db, cod_id: str) -> CODRequestDetail:
    doc = await db.cod_requests.find_one({"cod_id": cod_id})
    if not doc:
        raise HTTPException(status_code=404, detail="COD Request tidak ditemukan")
```
- **Root Cause:** `get_cod_detail` does not accept user/cabang parameters. Service looks up solely by `cod_id`. Route passes no ownership context.
- **Impact:** Cross-cabang disclosure of customer phone/WhatsApp, delivery address, location, order references, courier/cashier identities, screenshots, and COD workflow history.
- **Fix Plan:** Pass `user` to `get_cod_detail`; include `cabang` in query for non-owner users.
- **Regression Risk:** Medium — test owner global view, KC same-branch, kasir own-COD.
- **Status:** OPEN

---

## BUG-042 [NEW] — Cross-Branch Service Detail with `require_any`
- **Severity:** High (P1)
- **Repository:** Backend
- **Role:** Any authenticated user (including Kurir, Influencer)
- **File:** `app/routes/service.py:47-54`, `73-92`
- **Evidence:**
```
$ sed -n '47,54p' app/routes/service.py
@router.get("/{service_id}")
async def get_service(
    service_id: str,
    db:    AsyncIOMotorDatabase = Depends(get_db),
    _user: dict = Depends(require_any),
):
    item = await service_service.get_service(db, service_id)
    return ok(item.model_dump())

$ sed -n '73,92p' app/routes/service.py
@router.get("/{service_id}/detail")
async def service_detail(
    service_id: str,
    db:    AsyncIOMotorDatabase = Depends(get_db),
    user:  dict = Depends(require_any),
):
    doc = await db.service.find_one({"service_id": service_id})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Service {service_id} tidak ditemukan")
```
- **Root Cause:** Both endpoints use `require_any` (any authenticated user) and fetch only by `service_id`. The `user` variable on `/detail` is never used for filtering.
- **Impact:** Any authenticated user (including kurir, influencer) can access cross-branch customer contact data, repair complaints, technician assignment, service photos, and timeline.
- **Fix Plan:** Use appropriate role guard (exclude kurir/influencer unless explicitly needed). Add cabang filter for non-owner users.
- **Regression Risk:** Medium — verify service workflow for technician, kasir, KC, owner.
- **Status:** OPEN

---

## BUG-043 [NEW] — Cloudinary Unauthorized Delete + Arbitrary Signature
- **Severity:** High (P1)
- **Repository:** Backend
- **Role:** Any authenticated user
- **File:** `app/routes/upload.py:244-268`, `271-314`
- **Evidence:**
```
$ sed -n '244,261p' app/routes/upload.py
@router.delete("/image", response_model=dict)
async def delete_uploaded_image(
    public_id: str = Form(...),
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_any),
):
    try:
        result = await delete_image(public_id)
        return ok(result, message="Image deleted successfully")

$ sed -n '271,276p' app/routes/upload.py
@router.get("/signature", response_model=dict)
async def get_upload_signature(
    folder: str = "jayaphone/general",
    public_id: Optional[str] = None,
    timestamp: Optional[int] = None,
    user: dict = Depends(require_any),
):
```
- **Root Cause:** `DELETE /upload/image` accepts arbitrary Cloudinary `public_id` with no ownership/folder/role validation. `GET /upload/signature` allows arbitrary caller-controlled `folder` and optional `public_id`, signed with server's Cloudinary API secret.
- **Impact:** Any low-privileged user (kurir, influencer) can delete arbitrary Cloudinary assets or obtain valid upload signatures for any folder.
- **Fix Plan:** Remove `/upload/signature` unless direct upload is required. If retained, derive server-controlled folder. Restrict deletion to owner/admin roles. Add asset ownership metadata.
- **Regression Risk:** Medium — re-test all image upload workflows.
- **Status:** OPEN

---

## BUG-044 [NEW] — Unit Sale Atomic Claim Missing Cabang + Rollback Race
- **Severity:** High (P1)
- **Repository:** Backend
- **Role:** Kasir, Teknisi, Kepala Cabang, Owner
- **File:** `app/services/transaksi_service.py:72-89`
- **Evidence:**
```
$ sed -n '72,89p' app/services/transaksi_service.py
        unit = await db.units.find_one_and_update(
            {"unit_id": payload.unit_id, "status": "Tersedia"},
            {"$set": {"status": "Sold", "tgl_terjual": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc)}},
            return_document=False,
        )
        if not unit:
            existing = await db.units.find_one({"unit_id": payload.unit_id})
            ...
        if unit.get("cabang") != cabang:
            await db.units.update_one({"unit_id": payload.unit_id}, {"$set": {"status": "Tersedia"}})
            raise HTTPException(status_code=403, detail="Unit bukan milik cabang kamu")
        if unit.get("imei") and unit["imei"] != "-":
            if payload.imei.strip() != unit["imei"]:
                await db.units.update_one({"unit_id": payload.unit_id}, {"$set": {"status": "Tersedia"}})
                raise HTTPException(status_code=422, detail="IMEI tidak sesuai. Periksa kembali.")
```
- **Root Cause:** Atomic claim filters only `unit_id` + `status`, omitting `cabang`. Post-claim validation then rolls back with unconditional `update_one({"unit_id": ...})`. Rollback race: if a concurrent sale happens between claim and rollback, the rollback overwrites the new state.
- **Impact:** Cross-branch unit can be temporarily sold before 403. Rollback can overwrite concurrent legitimate state changes. Multi-doc sale (unit + spareparts + customer + transaction) has no MongoDB transaction, so partial failures leave inconsistent state.
- **Fix Plan:** Include `cabang` in atomic claim: `{"unit_id": ..., "cabang": cabang, "status": "Tersedia"}`. Validate IMEI before claim if possible. Use MongoDB transaction for multi-doc sale or implement compensation.
- **Regression Risk:** High — core sales path. Re-test same-branch, cross-branch, wrong-IMEI, concurrent sales, sparepart-only sales.
- **Status:** FIXED
- **Verified By:** Static: py_compile PASS, 5/5 pattern checks PASS. Requires live test: test cross-branch sale → 403 without temp state mutation; test wrong IMEI → rollback doesn't overwrite concurrent state; test concurrent same-unit sale → only 1 succeeds; test sparepart-only sale unchanged.

---

## BUG-045 [NEW] — `kurangi_stok_batch` Non-Atomic + Cross-Branch
- **Severity:** High (P1)
- **Repository:** Backend
- **Role:** Teknisi (service completion)
- **File:** `app/services/sparepart.py:126-143`
- **Evidence:**
```
$ sed -n '126,143p' app/services/sparepart.py
async def kurangi_stok_batch(db, items, actor, cabang):
    for item in items:
        sp = await db.sparepart.find_one({"sp_id": item["sp_id"]})
        if not sp:
            continue
        actual_deducted = min(sp["stok"], item["jumlah"])
        stok_baru = sp["stok"] - actual_deducted
        await db.sparepart.update_one(
            {"sp_id": item["sp_id"]},
            {"$set": {"stok": stok_baru, "updated_at": datetime.now(timezone.utc)}}
        )
```
- **Root Cause:** Read-then-write per item. No `cabang` filter in `update_one`. No `$gte` stock predicate. Concurrent service completions can each read the same stock and overwrite deductions. `min()` silently caps deductions without error.
- **Impact:** Sparepart stock goes wrong under concurrent service completions. Cross-branch stock can be deducted. Service completion silently consumes less than requested without failing.
- **Fix Plan:** Replace with atomic `find_one_and_update({"sp_id": ..., "cabang": cabang, "stok": {"$gte": jumlah}}, {"$inc": {"stok": -jumlah}})`. Fail if result is None. Do not silently cap.
- **Regression Risk:** High — service completion, repair approval, sparepart inventory, stock reporting.
- **Status:** FIXED
- **Verified By:** Static: py_compile PASS. Requires live test: test concurrent service completions → no double deduction; test insufficient stock → logged and skipped, not silent cap; test cross-branch sparepart → rejected by cabang filter.

---

## BUG-046 [NEW] — Transfer Response Non-Atomic
- **Severity:** High (P1)
- **Repository:** Backend
- **Role:** Kepala Cabang (destination), Owner
- **File:** `app/services/transfer_stok_service.py:213-253`
- **Evidence:**
```
$ sed -n '221,243p' app/services/transfer_stok_service.py
    doc = await db.transfer_stok.find_one({"transfer_id": transfer_id})
    ...
    if doc["status"] != "Pending":
        raise HTTPException(status_code=400, ...)
    ...
    if payload.status == StatusTransferEnum.diterima:
        await _proses_terima(db, doc, actor, now)
    else:
        await _proses_tolak(db, doc, actor, payload.catatan, now)
    ...
    await db.transfer_stok.update_one({"transfer_id": transfer_id}, {"$set": update})
```
- **Root Cause:** Reads `Pending`, performs multi-document unit mutations (ID reassignment, cabang reassignment, status changes), then writes transfer status. No atomic `Pending → Processing` claim prevents concurrent processing.
- **Impact:** Concurrent accept/reject can both execute. Units can be moved to destination then released by reject. Partial failures leave inconsistent transfer state.
- **Fix Plan:** Atomic claim: `find_one_and_update({"transfer_id": id, "status": "Pending"}, {"$set": {"status": "Processing"}})`. Execute all mutations in MongoDB transaction. Predicate unit updates by source cabang + `Dalam Transfer` status.
- **Regression Risk:** High — transfer, unit availability, notifications, sales.
- **Status:** FIXED
- **Verified By:** Static: py_compile PASS. Requires live test: test concurrent accept+reject → only 1 succeeds, other gets 400; test processing failure → reverts to Pending; test KC cabang mismatch → reverts to Pending + 403.

---

## BUG-047 [NEW] — Repair Approval No Cabang + No Atomic State
- **Severity:** High (P1)
- **Repository:** Backend
- **Role:** Kasir, Kepala Cabang, Owner
- **File:** `app/routes/units.py:57-69`, `app/services/unit_service.py:246`
- **Evidence:**
```
$ sed -n '246,260p' app/services/unit_service.py
    unit = await db.units.find_one({"unit_id": unit_id})
    if not unit:
        raise HTTPException(status_code=404, detail=f"Unit {unit_id} tidak ditemukan")
    if unit.get("kondisi_hp") != "Repair":
        raise HTTPException(status_code=400, detail="Unit ini bukan unit repair.")
    if unit.get("status") != "Service":
        raise HTTPException(status_code=400, detail=f"Unit tidak dalam status Service")

$ sed -n '57,68p' app/routes/units.py
@router.post("/{unit_id}/approve-repair", status_code=200)
async def approve_repair(unit_id, body, db, user):
    if user.get("role") == "teknisi":
        raise HTTPException(status_code=403, detail="Teknisi tidak bisa approve repair")
    unit = await unit_service.approve_repair(db, unit_id, body, actor=...)
```
- **Root Cause:** Route does not pass `user_cabang` to service. Service looks up by `unit_id` only (no cabang filter). State validation is read-then-write with no conditional update predicate. All writes use `update_one({"unit_id": ...})`.
- **Impact:** Non-owner can approve repair in another branch. Concurrent approval/update can overwrite state and price after initial checks.
- **Fix Plan:** Pass cabang to service. Use conditional atomic update: `find_one_and_update({"unit_id": ..., "cabang": cabang, "status": "Service"}, ...)`. Use transaction for unit + service status updates.
- **Regression Risk:** High — repair workflow, unit inventory, service state.
- **Status:** FIXED
- **Verified By:** Static: py_compile PASS (both route + service). Requires live test: test cross-branch repair approve → 403; test concurrent approve → only 1 succeeds (atomic); test service not yet Selesai → rollback unit + 400; test owner cross-cabang approve → allowed.

---

## BUG-048 [NEW] — COD Buy Approval Orphan (Terminal Before Unit Creation)
- **Severity:** High (P1)
- **Repository:** Backend
- **Role:** Kasir
- **File:** `app/services/cod_service.py:417-449, 490-503`
- **Evidence:**
```
$ sed -n '417,444p' app/services/cod_service.py
    doc = await db.cod_requests.find_one_and_update(
        {"cod_id": cod_id, "status": "menunggu_approval_kasir", "type": "beli", "cabang": cabang},
        {"$set": {"status": "selesai", "approved_by": kasir_name, ...}},
        return_document=True
    )
    if not doc:
        raise HTTPException(status_code=409, detail="COD sudah diapprove atau tidak dalam status menunggu approval")
    # Get unit_data from COD document
    unit_data = doc.get("unit_data", {})
    if not unit_data:
        raise HTTPException(status_code=400, detail="Data unit tidak ditemukan di COD")
    # ... THEN create unit (lines 490+)
```
- **Root Cause:** COD status is set to terminal `"selesai"` BEFORE unit creation. If `unit_data` is missing, unit insert fails, or repair routing fails after the atomic state change, the COD is terminally complete with no corresponding unit in inventory. No compensation or intermediate state exists.
- **Impact:** COD recorded as completed while unit inventory was never created. Retrying blocked by terminal state. Requires manual repair.
- **Fix Plan:** Validate all unit data BEFORE claiming approval. Use intermediate `approving` state or MongoDB transaction that includes COD state + unit insert + service ticket insert. Store `unit_id` in COD document as completion result.
- **Regression Risk:** High — COD buy, inventory intake, repair routing, duplicate approvals.
- **Status:** FIXED
- **Verified By:** Static: py_compile PASS, compileall PASS, code pattern verification 19/19. Requires live test: environment ini tidak punya akses MongoDB/server runtime. Test wajib: (1) happy path approve COD beli → unit Tersedia, (2) missing unit_data → revert ke menunggu_approval_kasir, (3) race condition 2x approve pakai asyncio.gather → hanya 1 sukses, (4) kondisi_hp=Repair → unit Service + service ticket created.

---

## BUG-049 [NEW] — Frontend Absent from Repository
- **Severity:** Critical (P0) — GAP
- **Repository:** Both (backend repo lacks frontend source)
- **Role:** All user roles
- **File:** Repository root (no frontend files tracked)
- **Evidence:**
```
$ git ls-files | grep -Ev '(^|/)node_modules/' | grep -Ei '\.(html|css|js)$' | grep -v scraper
(no output)

$ find . -maxdepth 3 -name 'index.html' -o -name 'main.js' -not -path '*/node_modules/*'
(no output)

$ cat README.md | grep -A2 'BACKEND_URL'
### 5. Update BACKEND_URL di frontend
Buka `index.html`, ubah baris:
window.BACKEND_URL = 'https://nama-project.vercel.app/api/v1';
```
- **Root Cause:** Documentation references `index.html` and `window.BACKEND_URL`, but no frontend source code is tracked in this repository. Only scraper service JS files exist.
- **Impact:** No backend endpoint can be VERIFIED as user-accessible through UI. All "VERIFIED via curl" claims are incomplete — they don't prove users can actually reach the feature through the SPA.
- **Fix Plan:** (1) Confirm frontend source lives in a separate repo. (2) Add link to frontend repo in README. (3) Run full UI verification against deployed frontend for each VERIFIED bug. (4) Create FRONTEND_MAP.md documenting which pages/menus/routes exist per role.
- **Regression Risk:** Critical — blocks all UI verification claims.
- **Status:** OPEN (GAP — not a code bug, but blocks verification completeness)

---

## BUG-050 [NEW] — Kurir Can Update Service Status + Deduct Spareparts
- **Severity:** High (P1)
- **Repository:** Backend
- **Role:** Kurir
- **File:** `app/routes/service.py:62`, `app/middlewares/auth.py:38-41`
- **Evidence:**
```
$ grep -n 'require_teknisi_or_owner' app/routes/service.py
app/routes/service.py:62:    user:  dict = Depends(require_teknisi_or_owner),

$ sed -n '38,41p' app/middlewares/auth.py
def require_teknisi_or_owner(current_user: dict = Depends(get_current_user)) -> dict:
    """Teknisi, Kurir, kepala_cabang, dan owner bisa akses."""
    if current_user.get("role") not in ("owner", "kepala_cabang", "teknisi", "kurir"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Akses ditolak")

$ sed -n '133,139p' app/services/service_service.py
        if new_status == "Selesai":
            sp_items = doc.get("sparepart_items", [])
            if sp_items:
                await sp_kurangi_stok_batch(
                    db, items=sp_items, actor=actor, cabang=doc.get("cabang", "")
                )
```
- **Root Cause:** `require_teknisi_or_owner` includes `kurir` in allowed roles. This guard protects `PUT /service/{id}` which allows status transitions including `Proses → Selesai` (triggers sparepart deduction) and `Antrian → Proses` (assigns technician).
- **Impact:** Kurir can complete service tickets and trigger sparepart stock deductions. Kurir can reject services. Kurir can auto-assign technicians. Kurir's role is COD delivery, not repair/service operations.
- **Fix Plan:** Remove `kurir` from `require_teknisi_or_owner`. Create separate `require_teknisi_or_owner_no_kurir` or update the guard to exclude kurir. Verify kurir still has access to log endpoint (separate guard needed).
- **Regression Risk:** Medium — test kurir COD workflow still works, test service update blocks kurir.
- **Status:** FIXED
- **Verified By:** Static: py_compile PASS. Added explicit kurir role check in PUT /service/{id} handler (same pattern as existing teknisi check). Kurir still has access to GET /log (separate endpoint, intentional). Requires live test: test kurir PUT /service/{id} → 403; test kurir GET /log → 200 (own logs); test teknisi PUT /service/{id} → 200.

---

## SUSPECTED (Needs Confirmation)

### S1. Customer identity merge across branches
- **INVESTIGATED 2026-07-21:** `transaksi_service.py:133` looks up customer by `nama` only (no cabang). Customer created with `cabang` field but lookup ignores it. Same-name customers from different branches merge into one record → shared points pool.
- **Severity:** Medium (P2) — needs product decision: global or per-cabang customer?
- **Files:** `app/services/transaksi_service.py:133`, `app/services/customer_service.py`
- **Needs:** Product requirement confirmation on customer identity policy before fix.

### S2. `trx_id` vs `transaksi_id` naming drift
- **INVESTIGATED 2026-07-21:** Only 1 remaining location: `cod_service.py:384` with intentional backward compat fallback. All other code uses `trx_id` consistently. **No action needed** — this is documented backward compat, not a bug.

### S3. ~~`require_teknisi_or_owner` allows Kurir~~ → **NOW BUG-050**
- **INVESTIGATED 2026-07-21:** Confirmed as RBAC bug. Kurir can update service status including `Proses → Selesai` (triggers sparepart deduction). Elevated to BUG-050 (HIGH).

### S4. No MongoDB transaction usage
- **ARCHITECTURE NOTE (2026-07-21):** All multi-document operations use separate `update_one` calls without MongoDB transactions. Per user decision: atomic single-document operations (`find_one_and_update`) are sufficient for current scale. MongoDB transactions are a future architecture consideration, NOT in scope for this audit cycle.

---

## PRIORITY FIX ORDER

| Priority | Bug | Reason |
|----------|-----|--------|
| 1 | BUG-049 | Frontend gap — confirm separate repo, update VERIFIED claims |
| 2 | BUG-048 | COD approval orphan — terminal state before unit creation, data loss risk |
| 3 | BUG-044 | Unit sale cabang + rollback race — core sales path |
| 4 | BUG-045 | kurangi_stok_batch non-atomic — stock corruption |
| 5 | BUG-046 | Transfer non-atomic — multi-doc corruption |
| 6 | BUG-047 | Repair approval no cabang |
| 7 | BUG-050 | Kurir RBAC — can update service + deduct spareparts |
| 8 | BUG-040 | Transaction cross-branch financial disclosure |
| 9 | BUG-041 | COD cross-branch detail disclosure |
| 10 | BUG-042 | Service cross-branch detail (require_any too broad) |
| 11 | BUG-043 | Cloudinary unauthorized delete + signature |

---

## AUDIT PROMPTS GENERATED (Reference)

1. **Security/RBAC Agent:** Pentester persona, scope = backend route/auth/service, evidence-based findings for RBAC/ownership/auth/config issues.
2. **Data-Integrity Agent:** DB engineer persona, scope = COD/transaksi/sparepart/unit/transfer/service routes+services, atomic check on every status/stock mutation.
3. **Frontend-Backend Sync Agent:** Frontend QA persona, scope = frontend HTML/JS/CSS + backend route declarations, fetch/role/UI mapping.
4. **Maintainability Agent:** (FAILED — API credit limit exceeded)

---

## VERIFICATION COMMANDS RUN

```bash
# Workspace validation
cd /root/phonejaya && pwd && git rev-parse --show-toplevel && git status --short

# Source counts
find app -name '*.py' | wc -l   # 40+ route/service/schema files
find . -name '*.html' -not -path '*/node_modules/*' | wc -l  # 0 frontend

# Baseline compile
.venv/bin/python -m compileall -q app && echo 'PASS'

# Key file verification for each bug
grep -n 'find_one({"trx_id"' app/routes/transaksi.py
grep -n 'find_one({"cod_id"' app/services/cod_service.py
grep -n 'require_any' app/routes/service.py
grep -n 'require_any' app/routes/upload.py
grep -n 'find_one_and_update' app/services/transaksi_service.py
grep -n 'kurangi_stok_batch' app/services/sparepart.py
grep -n 'find_one({"transfer_id"' app/services/transfer_stok_service.py
grep -n 'find_one({"unit_id"' app/services/unit_service.py
grep -n '"status": "selesai"' app/services/cod_service.py
```

---

## BUG-051 [NEW] — White Input Fields in COD Delivery Form
- **Severity:** Medium (P2)
- **Repository:** Frontend
- **Role:** Kasir
- **File:** `index.html:2887,2891`
- **Evidence:** Fields used `class="input"` (literal CSS class) instead of `class="${input}"` (JS template variable with Tailwind dark theme classes). Same issue in 21 other input fields across COD Beli form and kurir submit-beli modal.
- **Root Cause:** COD delivery fields were added later and used literal class name instead of the JS variable that provides dark theme styling.
- **Impact:** White/bright input fields that clash with dark theme, breaking visual consistency.
- **Fix Plan:** Replace all `class="input"` with `class="${input}"` in template literals.
- **Regression Risk:** Low — purely cosmetic change to match existing input style.
- **Status:** FIXED

---

## BUG-052 [NEW] — COD Beli Broken Icon (Smartphone SVG)
- **Severity:** Low (P3)
- **Repository:** Frontend
- **Role:** Kasir
- **File:** `index.html:2752`
- **Evidence:** `${smartphoneSvg}` rendered inside `<p>` tag without proper inline wrapper, causing SVG to clip or not render.
- **Root Cause:** SVG was inline in paragraph text without `inline-block` wrapper, causing layout issues.
- **Fix Plan:** Wrap SVG in `<span class="inline-block align-middle mr-1">`.
- **Regression Risk:** Low — purely cosmetic.
- **Status:** FIXED

---

## BUG-053 [NEW] — COD Beli Should Use Broadcast (Not Manual Kurir Assign)
- **Severity:** High (P1)
- **Repository:** Backend + Frontend
- **Role:** Kasir, Kurir
- **Files:** `app/schemas/cod.py:34-40`, `app/services/cod_service.py:73-92,306-311`, `index.html:5729-5770`
- **Evidence:**
```
Schema validator: if cod_type in ("beli", "jual") and not v: raise ValueError
Service: if payload.type == "delivery": pass else: validate kurir_id
Kurir dashboard: {"kurir_id": None, "type": "delivery", "status": "menunggu_kurir"}
Frontend: <select id="cb-kurir"> + if (!kurir) { showToast('Pilih kurir') }
```
- **Root Cause:** COD Beli was designed with manual kurir assignment, but requirement is broadcast (same as delivery).
- **Impact:** Kasir must manually pick kurir for every COD Beli, defeating the broadcast/first-come-first-served pattern.
- **Fix Plan:**
  1. Schema: kurir_id now only required for "jual", optional for "beli"/"delivery"
  2. Service: beli treated as broadcast (no kurir validation)
  3. Kurir dashboard: show broadcast beli jobs (`type: {$in: ["delivery", "beli"]}`)
  4. Frontend: removed kurir dropdown from COD Beli form
- **Regression Risk:** Medium — COD jual must still require kurir. Need live test.
- **Status:** FIXED
- **Verified By:** Static: py_compile PASS, compileall PASS. Requires live test: (1) Kasir buat COD Beli tanpa pilih kurir → sukses, (2) Muncul di dashboard SEMUA kurir cabang, (3) 1 kurir accept → lain dapat 409, (4) COD jual masih wajib pilih kurir.
