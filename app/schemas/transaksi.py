from pydantic import BaseModel, field_validator
from typing import Optional, List

from app.schemas.common import MAX_RUPIAH


class TransaksiCreateRequest(BaseModel):
    """Transaksi gabungan: HP +/ sparepart."""
    customer_type: str = "member"  # "member" | "guest"
    unit_id:  str = ""          # opsional — kosong kalau jual sparepart saja
    imei:          str = ""
    catatan:       str = ""
    garansi_hari:  int = 7     # 7 atau 30
    biaya_garansi: int = 0     # 0 atau 100000
    customer_nama: str = ""
    customer_kontak: str = ""
    poin_dipakai: int = 0
    sparepart_items: Optional[List["SparepartTrxItem"]] = None  # list sparepart yang dibeli
    foto_serah_terima: Optional[str] = None

    @field_validator("biaya_garansi", "poin_dipakai")
    @classmethod
    def not_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("Tidak boleh negatif")
        if v > MAX_RUPIAH:
            raise ValueError(f"Tidak boleh lebih dari {MAX_RUPIAH:,}")
        return v


class SparepartTrxItem(BaseModel):
    sp_id:   str
    jumlah:  int = 1

    @field_validator("jumlah")
    @classmethod
    def jumlah_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("Jumlah harus minimal 1")
        return v


class TransaksiSparepartItem(BaseModel):
    """Legacy — dipertahankan untuk backward compat."""
    sp_id:   str
    jumlah:  int = 1


class TransaksiSparepartRequest(BaseModel):
    """Legacy — endpoint /sparepart tetap ada untuk backward compat."""
    items:    List[TransaksiSparepartItem]
    catatan:  str = ""


class TransaksiResponse(BaseModel):
    id:          str
    trx_id:      str
    tipe:        str          # "unit" | "sparepart" | "gabungan"
    unit_id:     Optional[str] = None
    unit_label:  str
    kasir:       str
    harga_jual:  int
    harga_modal: int
    profit:      int
    waktu:       str
    catatan:      str
    garansi_hari: int = 7
    biaya_garansi: int = 0
    poin_dipakai: int = 0
    poin_dapat: int = 0
    cabang:       str
    customer_type: str = "member"  # "member" | "guest"
    customer_nama: str = ""
    customer_kontak: str = ""
    sp_items: Optional[list] = None
    foto_serah_terima: Optional[str] = None
    # Dibatalkan — baik manual (kasir/KC/owner) atau otomatis saat COD
    # delivery nego gagal di lokasi. Transaksi tidak punya konsep status
    # sebelum ini (record histori flat) — field ini murni additive, None
    # berarti masih aktif/berlaku.
    dibatalkan_at:      Optional[str] = None
    dibatalkan_oleh:    Optional[str] = None
    dibatalkan_alasan:  Optional[str] = None
    # Diamandemen — harga_jual/profit/poin_dapat diubah setelah kurir closing
    # nego di lokasi dengan harga akhir yang berbeda dari yang tercatat saat
    # transaksi dibuat. harga_jual_asli menyimpan angka sebelum amandemen
    # (harga_jual di atas sudah jadi angka terbaru).
    harga_jual_asli:    Optional[int] = None
    diamandemen_oleh:   Optional[str] = None
    diamandemen_at:     Optional[str] = None


class TransaksiVoidRequest(BaseModel):
    """Kasir/kepala cabang/owner batalkan transaksi yang sudah tercatat —
    mengembalikan unit/stok/poin. Ditolak kalau transaksi ini sudah
    terkirim ke customer lewat COD delivery (lihat guard di
    transaksi_service.void_transaksi)."""
    alasan: str

    @field_validator("alasan")
    @classmethod
    def alasan_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Alasan pembatalan wajib diisi")
        return v.strip()


# Fix forward reference
TransaksiCreateRequest.model_rebuild()
