# BUG.md — Phonejaya Backend

Generated: 2026-08-01 (Code-level audit session) · Updated: 2026-08-01 (fix pass)

## Status: all 22 findings below have been FIXED in code on this branch.

Commits: `ea563e9` (Critical/High, BUG-001..007), `21f616b` (Medium, BUG-008..016),
`c574a85` (Low, BUG-017,019..022). BUG-018 was fixed alongside BUG-010/011 in `21f616b`.

## Methodology

This report was produced by **static code audit** (route handlers + service layer + schemas +
middleware, read directly from source), **not** by hitting the live deployment. Fixes were then
applied directly in the local clone, verified with `py_compile` across `app/` after every change,
and (where practical) exercised with standalone unit-level scripts against a throwaway virtualenv
(e.g. the SSRF host-validator for BUG-007). None of this substitutes for hitting the real endpoints.

Live testing against `https://phonejaya.vercel.app` using the 6 provided role accounts
(owner/Rudi/bayu/fauzi/adit/firman) was the original plan for this session, but this session's
network egress policy blocks outbound access to `phonejaya.vercel.app` (proxy returns
`403 connect_rejected — policy denial`). That is an environment/session restriction, not a backend
issue. Every fix below is marked `NEEDS LIVE VERIFICATION` — re-run against the real deployment with
the 6 test accounts as soon as network access is available, starting with BUG-006 (should reproduce
and then resolve immediately and deterministically).

Do not treat the previous `BUG.md` (deleted in this cleanup) as ground truth — it referenced retired
test accounts and a different session's fix log. This file starts fresh from the current code on
branch `claude/jayaphone-phonejaya-logic-huswo7`.

---

## CRITICAL

### BUG-001 — `kepala_cabang` can mint an Owner account via `POST /karyawan`
- **Files:** `app/routes/karyawan.py:32-44`, `app/schemas/karyawan.py:22-28`, `app/services/karyawan_service.py:53-61`
- **Guard:** `require_kepala_or_owner` (owner, kepala_cabang)
- **Scenario:** The handler forces `body.cabang` to the caller's own cabang for `kepala_cabang`, but never restricts `body.jabatan`. `KaryawanCreateRequest.jabatan_valid` accepts `"Owner"`/`"Admin"`, and `karyawan_service.create_karyawan` maps that straight to `role: "owner"` when inserting into `db.users`. A logged-in `kepala_cabang` can call:
  ```
  POST /karyawan {"jabatan":"Owner","username":"x","password":"...","nama":"x","cabang":"..."}
  ```
  and receive a fully-privileged owner login with no owner-only check anywhere on this path. This is a complete privilege-escalation path from branch-head to full owner.
- **STATUS: FIXED** — `app/routes/karyawan.py` now 403s if a `kepala_cabang` caller submits `jabatan` in `("Owner", "Admin")`, before `create_karyawan` is ever called. **NEEDS LIVE VERIFICATION.**

---

## HIGH

### BUG-002 — No token revocation on employee deactivation/firing (up to 7-day stale access)
- **Files:** `app/middlewares/auth.py:7-16`, `app/services/cabang_service.py:107-111,163-192`, `app/config/settings.py:17` (`JWT_EXPIRE_MINUTES` = 7 days)
- **Scenario:** `get_current_user` trusts the `aktif` claim baked into the JWT at login time; it never re-checks the DB. `DELETE /cabang/karyawan/{id}` (fire) and the kepala_cabang-reassignment deactivation path both flip `users.aktif = False` in Mongo, but any token already issued to that user keeps `"aktif": true` and stays valid for up to `JWT_EXPIRE_MINUTES` (7 days) after firing.
- **Failure scenario:** Owner fires a cashier at 09:00. The cashier's existing session token (issued the day before) can still authenticate and hit any kasir-gated endpoint for up to 7 days.
- **STATUS: FIXED** — `get_current_user` now re-queries `db.users` by the JWT's `sub` on every request and rejects if `aktif` is false in the DB (also refreshes `role`/`cabang` from the DB in case they changed). Adds one DB round-trip per authenticated request — accepted tradeoff for real-time revocation. **NEEDS LIVE VERIFICATION**: fire a test employee, confirm their pre-fire token stops working immediately.

### BUG-003 — Concurrent `PUT /service/{id}` (Proses→Selesai) can double-decrement sparepart stock
- **File:** `app/services/service_service.py:80-165` (`update_service`)
- **Guard:** `require_teknisi_or_owner` (owner, kepala_cabang, teknisi — kurir explicitly 403'd in code)
- **Scenario:** `current_status` is read via a plain `find_one` (not an atomic claim), validated against `valid_transitions`, then `kurangi_stok_batch` runs, then the doc is persisted via an **unconditional** `update_one({"service_id": ...}, {"$set": updates})` with no `status` predicate. Two near-simultaneous `PUT` calls moving the same ticket `Proses → Selesai` both read `status="Proses"`, both pass validation, and both decrement sparepart stock — one repair, two stock deductions.
- **STATUS: FIXED** — status transition now goes through `find_one_and_update({"service_id":..., "status": current_status}, ...)` as an atomic claim before `kurangi_stok_batch` runs; the loser of a race gets a 409 instead of double-decrementing. **NEEDS LIVE VERIFICATION.**

### BUG-004 — `GET /transaksi/{trx_id}/detail` leaks financial data cross-branch
- **File:** `app/routes/transaksi.py:42-58`
- **Guard:** `require_kasir_teknisi_or_owner` (owner, kepala_cabang, kasir, teknisi)
- **Scenario:** The handler does `db.transaksi.find_one({"trx_id": trx_id})` with **no comparison against the caller's cabang anywhere in the function**. Combined with sequential, guessable `trx_id`s (`TRX-001`, `TRX-002`, …, per `app/utils/id_generator.py:28-32`), a kasir/teknisi from Branch A can enumerate `trx_id` values and pull `harga_modal`/`profit`/`margin_pct` for every branch's sales — exactly the data the RBAC model is supposed to hide from teknisi, exposed because `TransaksiResponse` never strips it for this role on the detail path.
- **STATUS: FIXED** — added an explicit `doc.cabang != user.cabang` → 403 check (owner exempt), matching the list endpoint's scoping. **NEEDS LIVE VERIFICATION.**

### BUG-005 — `GET /service/{id}` and `GET /service/{id}/detail` leak cross-branch data to kurir/influencer
- **Files:** `app/routes/service.py:47-54,77-96`, `app/services/service_service.py:65-69`
- **Guard:** `require_any` (any authenticated role, including kurir and influencer)
- **Scenario:** Neither handler filters by `doc.get("cabang")` vs. the caller's cabang — a bare `find_one({"service_id": ...})`. A kurir or influencer account (roles with no operational reason to see repair tickets at all) can fetch any branch's service ticket, including customer name/contact (PII) and repair cost fields.
- **STATUS: FIXED** — both `GET /service/{id}` and `GET /service/{id}/detail` now 403 when `doc.cabang != user.cabang` for non-owner roles, matching `list_service`'s existing scoping. **NEEDS LIVE VERIFICATION.**

### BUG-006 — Role-casing mismatch breaks COD "jual" creation and the kurir dropdown
- **Files:** `app/services/cod_service.py:84,408`, contrast `app/services/karyawan_service.py:56`
- **Scenario:** `db.users` stores the courier role as lowercase `"kurir"` (`role_map = {"Kurir": "kurir", ...}` at creation time), but `cod_service.py` queries `{"role": "Kurir", ...}` (capitalized) in both `create_cod_request` (validating the manually-assigned kurir for `type=jual`) and `get_kurir_list` (the kasir's kurir dropdown, `GET /cod/kurir-list`). Since no real user document has `role == "Kurir"`, **every "jual" COD creation request 404s** ("Kurir tidak ditemukan atau tidak aktif di cabang Anda") and the kurir dropdown always returns empty. This breaks the entire "jual" flow for kasir at the very first step.
- **STATUS: FIXED** — both queries now use `"role": "kurir"` (lowercase), matching how the role is actually stored. Grepped the rest of `app/` for other capitalized-role query literals — none found. **NEEDS LIVE VERIFICATION**: call `GET /cod/kurir-list` as kasir/bayu123 and confirm active kurir now show up.

### BUG-007 — SSRF via unvalidated TikTok video URL in influencer video submission
- **Files:** `app/services/tiktok_scraper.py:230` (`get_video_by_url`), called from `app/services/influencer_service.py:196` (`create_video`), route guard `app/routes/influencer.py:64` (`require_influencer`)
- **Scenario:** `VideoCreateRequest.url` (`app/schemas/influencer.py:18`) is a bare `HttpUrl` — nothing ties `platform="tiktok"` to an actual `tiktok.com` host. `get_video_by_url` issues `await self.client.get(video_url, ..., follow_redirects=True)` on the raw caller-supplied URL. Any authenticated influencer can `POST /influencer/videos` with `{"platform":"tiktok","url":"http://169.254.169.254/latest/meta-data/",...}` (or any internal host/port) and the backend will make that request server-side.
- **STATUS: FIXED** — `app/schemas/influencer.py` now validates that the URL's host matches an allowlist per declared platform (`tiktok.com`, `instagram.com`, `youtube.com`/`youtu.be`) for both `VideoCreateRequest` and `VideoCreateFetchRequest`, rejecting mismatched/spoofed hosts (e.g. `tiktok.com.evil.com`) at the schema layer before any HTTP call is made. Verified locally against 5 cases (legit URL, raw-IP SSRF attempt, subdomain-spoof attempt, legit Instagram URL, cross-platform mismatch) — all behaved correctly. **NEEDS LIVE VERIFICATION** for the end-to-end request path.

---

## MEDIUM

### BUG-008 — Non-atomic username check-then-insert race in employee creation
- **File:** `app/services/karyawan_service.py:26-70`
- **Scenario:** `create_karyawan` does `find_one` duplicate checks, then `insert_one` into `db.karyawan`, then a separate `insert_one` into `db.users`, with no transaction and no `try/except DuplicateKeyError` around the second insert. Unique indexes exist, so true duplicate logins can't land, but two concurrent creates with the same username can leave a `karyawan` doc inserted with no matching login account (the second `insert_one` throws an unhandled `DuplicateKeyError` → raw 500), unlike `assign_kepala_cabang`, which explicitly catches this case.
- **STATUS: FIXED** — both the `db.karyawan.insert_one` and `db.users.insert_one` calls are now wrapped in `try/except DuplicateKeyError`; a losing race returns a clean 409, and if the `users` insert fails after `karyawan` succeeded, the `karyawan` doc is deleted to avoid an orphan record. **NEEDS LIVE VERIFICATION.**

### BUG-009 — `transfer_stok` partial-failure leaves units migrated with no compensation
- **File:** `app/services/transfer_stok_service.py:304-370` (`_proses_terima`)
- **Scenario:** The per-unit acceptance loop updates each unit (reassign `unit_id`/`cabang`, set `Tersedia`) one at a time. If unit N+1 fails validation, the outer function reverts the **transfer document** to `Pending`, but units 1..N have already been migrated to the destination branch — there's no rollback of those unit writes. Retrying then fails again at the same point (units 1..N are no longer `"Dalam Transfer"`), permanently stalling the transfer while part of it has already silently moved cabang.
- **STATUS: FIXED** — split into two passes: pass 1 validates every unit in the transfer (existence, status, cabang) with zero mutation; pass 2 only runs (migrating units) after all units pass validation. A validation failure now mutates nothing. **NEEDS LIVE VERIFICATION.**

### BUG-010 — `POST /transaksi`: unit can be stranded as "Sold" with no transaction record
- **File:** `app/services/transaksi_service.py:77-133`
- **Scenario:** The unit is atomically claimed and set to `status: "Sold"` *before* the sparepart loop runs. If any sparepart item in that loop then fails (insufficient stock, unknown `sp_id`), an `HTTPException` is raised with no compensating rollback of the unit status. The unit ends up neither sellable (status != "Tersedia") nor accounted for (no `transaksi` doc was written). Rollback logic exists only for the earlier IMEI-mismatch case, not for failures later in the same function.
- **STATUS: FIXED** — see BUG-011 (same fix, same function).

### BUG-011 — Partial sparepart stock decrement on multi-item transaction failure
- **File:** `app/services/transaksi_service.py:108-125`
- **Scenario:** Each stock decrement inside the `sparepart_items` loop is individually atomic, but the loop itself isn't transactional — if item #1 decrements successfully and item #2 then fails ("stok tidak cukup"), item #1's stock reduction is never reversed, and repeated retries after seeing the error permanently bleed stock with no compensating transaksi record.
- **STATUS: FIXED** — `create_transaksi` now wraps unit-claim + sparepart-decrement + customer/points validation + the final `insert_one` in a single `try/except HTTPException` block. On any failure, the except clause reverts the claimed unit back to `"Tersedia"` and increments back every sparepart already decremented in this call, then re-raises. This closes both the unit-stranding (BUG-010) and partial-decrement (BUG-011) gaps with one rollback path. **NEEDS LIVE VERIFICATION**: force a mid-transaction failure (e.g. second sparepart item out of stock) and confirm the unit and first item's stock both revert.

### BUG-012 — Overlapping COD reject endpoints let a kurir skip the mandatory rejection reason
- **Files:** `app/routes/cod.py:125-137,140-156`, `app/services/cod_service.py:19` (`COD_BELI_FLOW`)
- **Scenario:** From COD-beli status `sudah_bertemu_penjual`, both the generic `POST /cod/kurir/{id}/reject` (optional `note`) and the dedicated `POST /cod/kurir/{id}/reject-beli` (mandatory `reason`) are valid transitions. A kurir can call the generic endpoint instead of the dedicated one to reject a beli COD after meeting the seller with **no reason at all**, defeating the intended business rule.
- **STATUS: FIXED** — `update_cod_status` (the generic path) now explicitly 400s when `type=="beli"`, `current=="sudah_bertemu_penjual"`, and `new_status=="ditolak"`, forcing the caller onto `reject-beli`. **NEEDS LIVE VERIFICATION.**

### BUG-013 — COD kurir monitoring silently drops all "delivery"-type stats
- **File:** `app/services/cod_service.py:772-834`
- **Scenario:** The `$group` aggregation counts `cod_beli`/`cod_jual` buckets but has none for `cod_delivery`. `status_proses` only lists beli/jual in-progress statuses, omitting the delivery-only states `kurir_menuju_toko`/`sedang_diantar`, and the terminal delivery status `terkirim` is never counted toward `total_done` (only `selesai`/`transaksi_berhasil` are). Result: completed/in-progress delivery jobs count toward `total_cod` but land in no per-status bucket, and `success_rate` undercounts delivery completions — courier performance/commission-relevant stats for the "delivery" type are silently wrong.
- **STATUS: FIXED** — added a `cod_delivery` counter, added `kurir_menuju_toko`/`sedang_diantar` to `status_proses`, added a `status_terkirim` counter, and included it in the `total_done`/`success_rate` calculation. **NEEDS LIVE VERIFICATION.**

### BUG-014 — Generic COD status endpoint can skip `submit-beli`, losing `deal_price`
- **Files:** `app/routes/cod.py:159-171`, `app/services/cod_service.py:19-24`, `app/schemas/cod.py:51-61,144-159`
- **Scenario:** `COD_STATUS_UPDATE` allows `menunggu_approval_kasir` as a literal target status, and the beli flow permits `input_stok → menunggu_approval_kasir`. A kurir can drive a beli COD to `menunggu_approval_kasir` purely via the generic `POST /cod/kurir/{id}/status` call, never calling `submit-beli`. `deal_price`/`unit_data` are then never written; on approval, `deal_price` silently defaults to `0`, and the resulting unit gets `harga_modal: 0` with no way for the kasir to correct the cost basis afterward.
- **STATUS: FIXED** — `update_cod_status` now explicitly 400s when `type=="beli"`, `current=="input_stok"`, and `new_status=="menunggu_approval_kasir"`, forcing the caller onto `submit-beli` (which requires `deal_price`/`unit_data`). **NEEDS LIVE VERIFICATION.**

### BUG-015 — Synchronous, unbounded TikTok metrics fetch can hang/timeout `POST /influencer/videos`
- **Files:** `app/services/influencer_service.py:194-215`, `app/services/tiktok_scraper.py:87-108`
- **Scenario:** `create_video` awaits the TikTok fetch directly with no overall `asyncio.wait_for` deadline. Each HTTP call has its own 30s timeout, but the fetch can chain multiple requests (bootstrap + profile + video page), so the whole request can run 60–90s+ — on Vercel serverless this risks 504s, and it's exploitable in combination with BUG-007 (SSRF): a slow/hanging target host can hang the request for the full chained timeout.
- **STATUS: FIXED** — both the TikTok and Instagram metrics fetches are now wrapped in `asyncio.wait_for(..., timeout=20)`; a timeout is caught and logged the same way an existing scraper error is (metrics stay 0, retried later by the cron sync). **NEEDS LIVE VERIFICATION.**

### BUG-016 — `DELETE /upload/image` has no ownership/resource-binding check
- **File:** `app/routes/upload.py:244-268`
- **Guard:** `require_any` (any authenticated role, including kurir and influencer)
- **Scenario:** The handler takes only `public_id` and calls `delete_image(public_id)` unconditionally — no check that the caller uploaded or otherwise owns that image, and no `write_log` call at all (unlike other influencer/upload mutations). Any authenticated user who obtains or guesses a `public_id` can permanently delete images belonging to units/services/customers in other branches, with no audit trail.
- **STATUS: FIXED** — added `cloudinary_service.get_resource_uploader()`, which reads the `uploaded_by` context stamped on the asset at upload time. The delete route now 403s for non-owner callers whose name doesn't match that context (fail-closed if the context is missing, e.g. legacy pre-fix assets), and logs every successful deletion via `write_log`. **NEEDS LIVE VERIFICATION** — also note legacy assets uploaded before this fix have no `uploaded_by` context and will be undeletable by non-owners going forward; only an owner can clean those up.

---

## LOW

### BUG-017 — `GET /units/{id}/modal-history` is dead — always returns empty
- **File:** `app/services/unit_modal_history.py:28` (`create_modal_history`, zero callers anywhere in `app/`)
- The one place that changes a unit's `harga_modal` post-creation (`request_sparepart_service.approve_request`) only writes to the generic `log` collection and explicitly comments this as a known limitation. The modal-history feature/endpoint is non-functional, not a security issue.
- **STATUS: FIXED** — `request_sparepart_service.approve_request` now also calls `create_modal_history(...)` alongside its existing `write_log` call, so `GET /units/{id}/modal-history` returns real entries going forward. Pre-fix history is not backfilled. **NEEDS LIVE VERIFICATION.**

### BUG-018 — Duplicate `trx_id` generation wastes a sequence number on member transactions
- **File:** `app/services/transaksi_service.py:170,217`
- `next_trx_id(db)` is called once at line 170 (result unused) and again at line 217 for the actual write — every member-flow transaction burns an extra sequence number and DB round-trip, producing permanent gaps in TRX numbering. `create_transaksi_sparepart` calls it correctly (once).
- **STATUS: FIXED** — the unused early call was removed as part of the BUG-010/011 rewrite of `create_transaksi`; `next_trx_id(db)` is now called exactly once, at doc-construction time.

### BUG-019 — Stale rejection metadata survives customer resubmit → approve
- **File:** `app/services/customer_service.py:293-333` (resubmit), `208-245` (approve)
- `resubmit_customer` never clears `rejected_reason`/`rejected_by`/`rejected_at`. If the customer is later approved, `CustomerResponse` still returns the old rejection reason alongside `status: Verified` — a stale, potentially misleading field for any UI consuming it.
- **STATUS: FIXED** — `resubmit_customer` now `$unset`s `rejected_at`/`rejected_by`/`rejected_by_name`/`rejected_by_role`/`rejected_reason` in the same update that sets status back to `Pending`. **NEEDS LIVE VERIFICATION.**

### BUG-020 — Concurrent customer approve/reject can duplicate `status_history` entries
- **File:** `app/services/customer_service.py:215,236,256,281`
- Read-then-write (`find_one` then `update_one`, no atomic claim). Two concurrent approve calls on the same Pending customer both pass validation and both append a `status_history` entry — end state is harmless but the audit trail is doubled.
- **STATUS: FIXED** — `approve_customer`, `reject_customer`, and `resubmit_customer` all now claim the transition atomically via `find_one_and_update({"_id":..., "status": current_status}, ...)`; a losing concurrent call gets a 409 instead of writing a duplicate history entry. **NEEDS LIVE VERIFICATION.**

### BUG-021 — Cron secret compared with `!=` instead of constant-time comparison
- **File:** `app/routes/influencer.py:230-234`
- `x_cron_secret != cron_secret` short-circuits on the first differing byte (timing side channel) instead of using `hmac.compare_digest`. Low practical exploitability over a real network, but it's the sole gate on `POST /influencer/sync/cron`.
- **STATUS: FIXED** — swapped to `hmac.compare_digest(x_cron_secret, cron_secret)`.

### BUG-022 — `GET /transfer-stok/notif/count` leaks a real pending-transfer count to influencer/kurir
- **Files:** `app/routes/transfer_stok.py:107-128`, `app/services/transfer_stok_service.py:417-425`
- **Guard:** `require_any`
- Both influencer and kurir user documents carry a `cabang` field, so this is not naturally empty for them — both roles receive a genuine non-zero pending-inbound-transfer count for a workflow they have no operational role in. Low severity (integer only, no line items) but not harmless-by-construction.
- **STATUS: FIXED** — guard changed from `require_any` to `require_kepala_or_owner`, matching every other endpoint in this module. **NEEDS LIVE VERIFICATION** — confirm this doesn't break a frontend badge that currently polls this endpoint for kurir/influencer accounts (if the frontend does that, it should stop, since those roles were never meant to see this count).

---

## Summary table

| ID | Severity | Area | One-line | Status |
|----|----------|------|----------|--------|
| BUG-001 | Critical | Karyawan | kepala_cabang can create an Owner account | FIXED |
| BUG-002 | High | Auth | Fired employee's token still works up to 7 days | FIXED |
| BUG-003 | High | Service | Concurrent PUT can double-decrement sparepart stock | FIXED |
| BUG-004 | High | Transaksi | Detail endpoint leaks cross-branch financial data | FIXED |
| BUG-005 | High | Service | Detail endpoints leak cross-branch data to kurir/influencer | FIXED |
| BUG-006 | High | COD | "Kurir" vs "kurir" casing breaks jual COD + dropdown | FIXED |
| BUG-007 | High | Influencer | SSRF via unvalidated TikTok video URL | FIXED |
| BUG-008 | Medium | Karyawan | Non-atomic username check-then-insert race | FIXED |
| BUG-009 | Medium | Transfer Stok | Partial-failure leaves units migrated with no rollback | FIXED |
| BUG-010 | Medium | Transaksi | Unit stranded "Sold" on partial transaction failure | FIXED |
| BUG-011 | Medium | Transaksi | Partial sparepart decrement not reversed on later failure | FIXED |
| BUG-012 | Medium | COD | Overlapping reject endpoints bypass mandatory reason | FIXED |
| BUG-013 | Medium | COD | Monitoring aggregation drops delivery-type stats | FIXED |
| BUG-014 | Medium | COD | Generic status endpoint bypasses submit-beli, loses deal_price | FIXED |
| BUG-015 | Medium | Influencer | Synchronous unbounded TikTok fetch can hang request | FIXED |
| BUG-016 | Medium | Upload | DELETE /upload/image has no ownership check | FIXED |
| BUG-017 | Low | Units | Modal-history endpoint is dead code, always empty | FIXED |
| BUG-018 | Low | Transaksi | Duplicate trx_id generation wastes sequence numbers | FIXED |
| BUG-019 | Low | Customer | Stale rejection metadata survives resubmit→approve | FIXED |
| BUG-020 | Low | Customer | Concurrent approve/reject duplicates status_history | FIXED |
| BUG-021 | Low | Influencer | Cron secret compared non-constant-time | FIXED |
| BUG-022 | Low | Transfer Stok | notif/count leaks pending-transfer count to influencer/kurir | FIXED |

**All 22 findings are fixed in code and pushed to `claude/jayaphone-phonejaya-logic-huswo7`.**
**None have been exercised against the live deployment — network access to `phonejaya.vercel.app` was
blocked for this whole session. Run the 6-account live pass from the original task before merging.**
