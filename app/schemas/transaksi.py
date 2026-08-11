from pydantic import BaseModel, field_validator
from typing import Optional, List


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


# Fix forward reference
TransaksiCreateRequest.model_rebuild()
