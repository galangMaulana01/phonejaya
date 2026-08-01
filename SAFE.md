# SAFE.md — Phonejaya Backend

Generated: 2026-08-01 (Code-level audit session)

## Purpose

This file lists endpoints/mechanisms that were read line-by-line during this audit and confirmed
**clean** — no RBAC bypass, no cross-cabang leak, and (where relevant) atomic/race-safe writes.
Goal: future sessions don't need to re-read these from scratch. If you change any of the referenced
files, re-verify the specific claim below rather than trusting it blindly.

Audited via static code read (route + service + schema + middleware), not live HTTP calls — this
session's network egress policy blocked outbound access to `phonejaya.vercel.app`. Where a live
check would meaningfully add confidence, it's noted as `NEEDS LIVE VERIFICATION`.

---

## Auth / Karyawan / Cabang

- **JWT expiry enforcement** — `app/utils/security.py:36-50` + `app/middlewares/auth.py:12-13`. Expired tokens are explicitly rejected with 401 (re-decoded with `verify_exp: False` only to tag `_expired`, then rejected). Confirmed still fixed from any prior known issue.
- **Password hashing** — `app/utils/security.py:13-23`. bcrypt via `gensalt`/`hashpw`/`checkpw`; `verify_password` safely handles malformed hashes. No plaintext storage path.
- **`GET /karyawan` cabang scoping** — `app/routes/karyawan.py:23-26`. Non-owner's `cabang` query param is unconditionally overridden with `user.get("cabang")` — a kepala_cabang cannot list another branch's staff.
- **`GET /karyawan/{id}/stats` cross-branch guard** — `app/routes/karyawan.py:87-89`. Explicit `kar.get("cabang") != user.get("cabang")` check with 403 for kepala_cabang, narrower than the route's declared guard alone would allow.
- **Own-password change flow** — `app/routes/auth.py:106-146`. Requires verified old password, updates only the caller's own `_id` from the JWT subject, no role field touched — no escalation path here.
- **Cabang org-structure mutations** — `POST/PATCH /cabang`, `POST /cabang/{kode}/kepala`, `DELETE /cabang/karyawan/{id}` all use `require_owner` with no contradicting manual checks; correctly owner-only.
- **Unique indexes** — `app/config/database.py:57,60,63`. Unique indexes on `users.username`, `karyawan.username`, `cabang.kode` close most duplicate-account races at the DB layer (see BUG-008 for the remaining narrow race).

## Units / Sparepart / Transfer Stok

- **`POST /units` cabang forcing** — `app/routes/units.py:46-47`. Owner keeps submitted `cabang`; every non-owner role is forced to their own — no injection path.
- **`POST /units/{id}/approve-repair` cross-branch check** — `app/services/unit_service.py:254-285`. Despite the route guard alone being broader, the service's atomic `find_one_and_update` filter includes `{"cabang": user_cabang}` for non-owners and explicitly 403s ("Unit bukan milik cabang Anda") on mismatch. A previously-flagged concern about kasir approving a foreign-branch unit is **refuted**.
- **Transfer-stok create/respond atomicity** — `app/services/transfer_stok_service.py:170-183` (create lock via `update_many` + rollback) and `222-268` (respond claim via `find_one_and_update` status `Pending→Processing` with revert-on-exception). Both correctly prevent a unit being "in transfer" twice or a transfer double-processed. (The one gap is the partial-failure case inside `_proses_terima`, tracked as BUG-009.)
- **`request_sparepart` approve role check** — `app/routes/request_sparepart.py:80-92` declares `require_any`, but `app/services/request_sparepart_service.py:174-183` explicitly checks `actor_role == "kasir"` and uses an atomic, cabang-scoped `find_one_and_update` claim. A previously-flagged concern about influencer/kurir approving sparepart requests is **refuted**.
- **Sparepart stock decrement atomicity** — `app/services/sparepart.py:87-155` (`update_stok`, `kurangi_stok_batch`). Both use `find_one_and_update` with an `$gte` stock predicate — cannot go negative or race at the single-item level.
- **`unit_modal_history` cabang check** — `app/routes/unit_modal_history.py:24-28`. Fetches the actual unit and compares `unit.cabang != user.cabang` (not just role) before allowing access.

## Transaksi / Customer / Service

- **Unit sale claim race** — `app/services/transaksi_service.py:79-83`. Atomic `find_one_and_update` filtered on `unit_id + cabang + status:"Tersedia"` prevents double-sale and cross-branch sale of the same unit.
- **Sparepart stock race (single item)** — `app/services/transaksi_service.py:116-120,264-268`. Atomic check-and-decrement (`stok:{"$gte":jumlah}`) prevents oversell per item (the multi-item-loop compensation gap is tracked separately as BUG-011).
- **`PUT /service/{id}` cabang ownership** — `app/services/service_service.py:84-87`. Explicit `doc.cabang != user_cabang` check for all non-owner roles — a teknisi cannot update another branch's ticket even though the route's declared guard is broader than needed.
- **`GET /transaksi` and `GET /service` list endpoints** — `app/routes/transaksi.py:22`, `app/routes/service.py:15-18,31`. Both correctly force `cabang = user.cabang` for non-owner roles. (Only the *single-record detail* endpoints for these two resources have the leak — see BUG-004/BUG-005.)
- **Customer duplicate-contact check** — `app/services/customer_service.py:92-95`. Uniqueness is scoped to `kontak + cabang`, correctly allowing the same phone number to exist as separate customer records across different branches.

## COD (Courier)

- **Broadcast atomic claim** — `app/services/cod_service.py:212-248`. `find_one_and_update` on `status:"menunggu_kurir"` + null `kurir_id` atomically assigns the courier in one op — two couriers cannot both claim the same beli/delivery broadcast.
- **Approve idempotency / single-unit guarantee** — `app/services/cod_service.py:430-455,518,536-555`. Atomic claim to `processing_approval` gated on `status + type + cabang`; a duplicate/concurrent approve call gets `doc=None` → 409. Exactly one inventory unit is ever created per approved COD-beli, with `_revert` restoring state on failure paths.
- **Cross-type transition safety** — `app/services/cod_service.py:260-271`. `update_cod_status` always resolves the flow from the persisted document's own `type`, never from caller input — a "jual" transition function cannot be misapplied to a "beli" record via the generic status endpoint.
- **Non-broadcast ownership enforcement** — `app/services/cod_service.py:255-257,274`. Requires `doc.kurir_id == actor` before any status write, and the write itself is an atomic `find_one_and_update` gated on the current status.
- **Cross-cabang isolation** — kurir dashboard (`cod_service.py:313-319`) filters `cabang == self.cabang` + `kurir_id == self`; kasir/KC list (`cod_service.py:344-345`) filters `cabang == user.cabang` for non-owners; `approve_beli_cod`/`reject_beli_cod` independently re-check `cabang` in their own atomic filters — a kasir cannot act on another branch's COD even if they know the `cod_id`.
- **Unit cabang propagation on COD approval** — `app/services/cod_service.py:506,527`, `app/services/unit_service.py:53`. The approving kasir's own cabang is what lands on the newly created unit — no cross-branch inventory injection.

## Influencer / Upload / Dashboard / Log

- **`GET /dashboard/stats`, `GET /dashboard/trend`** — `app/routes/dashboard.py:21,35`. `cabang` is unconditionally set to the owner's chosen filter or the caller's own cabang for kepala_cabang — no attacker-controlled cabang reaches the service layer for non-owners.
- **`GET /log` role_filter** — `app/routes/log.py:36-37`. The `role_filter` param is only honored for owner/kepala_cabang; for teknisi/kurir it's silently ignored and their query stays pinned to their own name — no cross-role leak.
- **`GET /influencer/catalog` has_video flag** — `app/services/influencer_service.py:110-156`. Video counts are built only from the caller's own `influencer_id`, and the units query is scoped to the caller's own `cabang` — no cross-influencer or cross-branch data included.
- **`owner_influencer.py` is confirmed dead** — `app/main.py:15,132` imports/registers only `influencer`, not `owner_influencer`. Its 3 endpoints are unreachable in production; equivalent functionality is duplicated inline in `influencer.py:184-219`. Not a live attack surface — don't spend test time on `/api/v1/owner/influencers/*`, expect 404.
- **`log_service.write_log` input handling** — `app/services/log_service.py:19-37`. Proper field-length caps and control-character/XSS-pattern stripping before Mongo insert.

---

## What this file does NOT cover

All 22 findings in `BUG.md` have since been fixed in code (commits `ea563e9`, `21f616b`, `c574a85`
on this branch) — but none of those fixes have been exercised against the live deployment, since
network access to `phonejaya.vercel.app` was blocked for this whole session. Don't move a `BUG.md`
entry's claim into this file until it's actually been hit live and confirmed; "fixed in code" and
"confirmed safe" are not the same status yet.

A few areas were audited only for the specific concerns listed in `BUG.md` and may have other
untouched surface (e.g. full Cloudinary upload-side validation, full schema-level input validation
across all 22 route files, and any logic reachable only from the frontend's specific request shapes).
Re-run a live check against the 6 test accounts once network access is available — start with
BUG-006 (COD "jual"/kurir dropdown), which should reproduce-then-resolve deterministically on the
first request.
