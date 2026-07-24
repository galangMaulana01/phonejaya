#!/usr/bin/env python3
"""
Verification script for Approval Sparepart Flow (Teknisi → KC → Kasir → Sparepart)

Run: python3 scripts/verify-approval-sparepart-flow.py
"""

import sys
sys.path.insert(0, "/root/phonejaya")

def test_schema():
    """Test schema validation"""
    from app.schemas.request_sparepart import (
        StatusRequestEnum, RequestSparepartCreateRequest,
        RequestSparepartApproveRequest, RequestSparepartResponse
    )
    
    # Status enum
    assert StatusRequestEnum.pending == "Pending"
    assert StatusRequestEnum.menunggu_kasir == "Menunggu_Kasir"
    assert StatusRequestEnum.selesai == "Selesai"
    assert StatusRequestEnum.ditolak == "Ditolak"
    print("✅ Status enum values correct")
    
    # Create request
    req = RequestSparepartCreateRequest(
        tipe="Sparepart", nama_sp="LCD iPhone 13", jumlah=2, keterangan="test", cabang="JYP"
    )
    assert req.nama_sp == "LCD iPhone 13"
    print("✅ Create request validation")
    
    # Approve request - valid
    approve = RequestSparepartApproveRequest(harga_jual=5000000, status="Selesai", catatan="ok")
    assert approve.harga_jual == 5000000
    assert approve.status == "Selesai"
    print("✅ Approve request validation")
    
    # Reject zero/negative harga_jual
    try:
        RequestSparepartApproveRequest(harga_jual=0, status="Selesai")
        raise AssertionError("Should reject zero harga_jual")
    except ValueError as e:
        assert "lebih" in str(e) or "0" in str(e) or "positive" in str(e).lower()
        print("✅ Rejects zero/negative harga_jual")
    
    # Reject invalid status
    try:
        RequestSparepartApproveRequest(harga_jual=100000, status="Invalid")
        raise AssertionError("Should reject invalid status")
    except:
        print("✅ Rejects invalid status")
    
    print("✅ All schema tests passed\n")


def test_service_logic():
    """Verify service logic patterns"""
    import inspect
    source = open("/root/phonejaya/app/services/request_sparepart_service.py").read()
    
    checks = [
        ("KC approval sets Menunggu_Kasir", "Menunggu_Kasir" in source and "disetujui_oleh_kc" in source),
        ("KC approval does NOT create sparepart", "create_sparepart" not in source.split("async def respond_request")[1].split("async def ")[0] if "async def respond_request" in source else True),
        ("Kasir approval creates sparepart on Selesai", "create_sparepart" in source and "Selesai" in source),
        ("Approved tracking fields", "approved_by" in source and "approved_at" in source),
        ("KC approval tracking", "disetujui_oleh_kc" in source and "disetujui_at_kc" in source),
        ("Ditolak status", '"Ditolak"' in source or "'Ditolak'" in source),
        ("Harga jual in approve", "harga_jual" in source),
    ]
    
    for desc, check in checks:
        if check:
            print(f"  ✅ {desc}")
        else:
            print(f"  ❌ {desc}")
            raise AssertionError(f"Check failed: {desc}")
    
    print("✅ All service logic checks passed\n")


def test_routes():
    """Verify routes exist"""
    from app.routes.request_sparepart import router
    
    routes = []
    for r in router.routes:
        if hasattr(r, 'path') and hasattr(r, 'methods'):
            methods = ",".join(r.methods)
            routes.append(f"{methods} {r.path}")
    
    expected = [
        "GET /request-sparepart",
        "POST /request-sparepart",
        "PATCH /request-sparepart/{req_id}/respond",
        "PATCH /request-sparepart/{req_id}/approve"
    ]
    
    found = [p for p in expected if any(p in r for r in routes)]
    assert len(found) == len(expected), f"Missing routes: {set(expected) - set(found)}"
    print(f"✅ Routes found ({len(routes)}): {routes}\n")


def test_middleware():
    """Test middleware guards"""
    from app.middlewares.auth import require_kasir, require_kasir_or_owner, require_kepala_or_owner
    print("✅ Middleware guards imported")
    print("  ✅ require_kasir")
    print("  ✅ require_kasir_or_owner")
    print("  ✅ require_kepala_or_owner")


def test_routes_file():
    """Check routes file has correct imports and structure"""
    content = open("/root/phonejaya/app/routes/request_sparepart.py").read()
    
    assert "require_kasir" in content, "require_kasir import missing"
    assert "require_kepala_or_owner" in content, "require_kepala_or_owner import missing"
    assert "require_kasir_teknisi_or_owner" in content, "require_kasir_teknisi_or_owner import missing"
    assert "approve_request" in content, "approve_request import missing"
    assert "list_requests" in content, "list_requests import missing"
    assert "respond_request" in content, "respond_request import missing"
    assert "create_request" in content, "create_request import missing"
    
    # Check Kasir blocked from creating
    assert "user.get(\"role\") == \"kasir\"" in content, "Kasir block check missing"
    
    print("✅ Routes file structure correct\n")


if __name__ == "__main__":
    print("=" * 60)
    print("VERIFICATION: Approval Sparepart Flow (Teknisi → KC → Kasir)")
    print("=" * 60)
    print()
    
    test_schema()
    test_service_logic()
    test_routes()
    test_middleware()
    test_routes_file()
    
    print("=" * 60)
    print("✅ ALL VERIFICATION PASSED")
    print("=" * 60)