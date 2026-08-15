import unittest
from fastapi import HTTPException

from app.middlewares.auth import require_teknisi_or_owner
from app.schemas.transaksi import SparepartTrxItem, TransaksiSparepartItem
from app.utils.upload_urls import ensure_uploaded_asset


class BlockerRegressionTests(unittest.TestCase):
    def test_negative_sparepart_quantity_is_rejected(self):
        with self.assertRaises(ValueError):
            SparepartTrxItem(sp_id="SP-1", jumlah=0)
        with self.assertRaises(ValueError):
            TransaksiSparepartItem(sp_id="SP-1", jumlah=-1)

    def test_kurir_cannot_use_teknisi_guard(self):
        with self.assertRaises(HTTPException) as exc:
            require_teknisi_or_owner({"role": "kurir"})
        self.assertEqual(exc.exception.status_code, 403)

    def test_only_storage_url_is_accepted_as_evidence(self):
        with self.assertRaises(HTTPException) as exc:
            ensure_uploaded_asset("https://attacker.invalid/fake-proof.jpg")
        self.assertEqual(exc.exception.status_code, 422)
        ensure_uploaded_asset("https://res.cloudinary.com/demo/image/upload/v1/proof.jpg")


if __name__ == "__main__":
    unittest.main()
