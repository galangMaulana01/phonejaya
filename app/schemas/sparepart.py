from pydantic import BaseModel, field_validator
from typing import Optional


class SparepartCreateRequest(BaseModel):
    nama:        str
    kategori:    str = "Umum"   # Umum / Packaging / LCD / Baterai / dll
    satuan:      str = "pcs"
    stok:        int = 0
    harga_beli:  int = 0
    harga_jual:  int = 0
    # Dimensi opsional — untuk kardus/packaging
    dimensi_p:   Optional[float] = None   # panjang (cm)
    dimensi_l:   Optional[float] = None   # lebar (cm)
    dimensi_t:   Optional[float] = None   # tinggi (cm)
    catatan:     str = ""
    cabang:      str = "JYP"
    product_link: Optional[str] = None

    @field_validator("nama")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Nama sparepart tidak boleh kosong")
        if len(v.strip()) > 200:
            raise ValueError("Nama sparepart maksimal 200 karakter")
        return v.strip()

    @field_validator("stok", "harga_beli", "harga_jual")
    @classmethod
    def non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("Nilai tidak boleh negatif")
        return v

    @field_validator("product_link")
    @classmethod
    def validate_product_link(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v.strip() == "":
            return None
        v = v.strip()
        if not v.startswith("https://"):
            raise ValueError("Link produk harus menggunakan HTTPS")
        return v


class SparepartUpdateStokRequest(BaseModel):
    """Tambah atau kurangi stok manual oleh owner."""
    delta:    int      # positif = tambah, negatif = kurangi
    catatan:  str = ""


class SparepartResponse(BaseModel):
    id:          str
    sp_id:       str
    nama:        str
    kategori:    str
    satuan:      str
    stok:        int
    harga_beli:  int
    harga_jual:  int
    dimensi_p:   Optional[float] = None
    dimensi_l:   Optional[float] = None
    dimensi_t:   Optional[float] = None
    catatan:     str
    cabang:      str
    dimensi_str: str   # "12 x 5 x 10 cm" atau ""
