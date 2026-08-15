from pydantic import BaseModel, field_validator
from typing import Optional

from app.schemas.common import MAX_RUPIAH

# repair: dipakai teknisi buat perbaikan, nambah modal HP yang direpair.
# dijual: dijual langsung ke customer lewat modul Transaksi, punya harga_jual sendiri.
# equipment: alat kerja teknisi yang tidak habis pakai (bukan dipakai/dijual per-unit).
SPAREPART_JENIS = {"repair", "dijual", "equipment"}
DEFAULT_SPAREPART_JENIS = "repair"


class SparepartCreateRequest(BaseModel):
    nama:        str
    kategori:    str = "Umum"   # Umum / Packaging / LCD / Baterai / dll
    jenis:       str = DEFAULT_SPAREPART_JENIS
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

    @field_validator("jenis")
    @classmethod
    def jenis_valid(cls, v: str) -> str:
        if v not in SPAREPART_JENIS:
            raise ValueError(f"Jenis harus salah satu dari: {', '.join(sorted(SPAREPART_JENIS))}")
        return v

    @field_validator("stok", "harga_beli", "harga_jual")
    @classmethod
    def non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("Nilai tidak boleh negatif")
        if v > MAX_RUPIAH:
            raise ValueError(f"Nilai tidak boleh lebih dari {MAX_RUPIAH:,}")
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

    @field_validator("delta")
    @classmethod
    def delta_bounded(cls, v: int) -> int:
        # Tidak ada validasi apapun di sini sebelumnya — konfirmasi live:
        # delta=99999999999999999999 diterima 200 dan menghasilkan stok yang
        # tidak masuk akal. Dibatasi ke rentang yang sama dengan harga, bukan
        # karena secara bisnis delta stok sebesar itu masuk akal, tapi supaya
        # angka absurd gagal jadi 422 yang jelas, bukan korupsi data diam-diam.
        if abs(v) > MAX_RUPIAH:
            raise ValueError(f"Perubahan stok tidak boleh lebih dari {MAX_RUPIAH:,} (absolut)")
        return v


class SparepartResponse(BaseModel):
    id:          str
    sp_id:       str
    nama:        str
    kategori:    str
    jenis:       str = DEFAULT_SPAREPART_JENIS
    satuan:      str
    stok:        int          # sisa yang BEBAS — sudah dipotong tiap kali dipakai/direservasi
    dipakai:     int = 0      # total sedang dipakai teknisi, dijumlahkan lintas tiket Proses/Menunggu_Sparepart
    harga_beli:  int
    harga_jual:  int
    dimensi_p:   Optional[float] = None
    dimensi_l:   Optional[float] = None
    dimensi_t:   Optional[float] = None
    catatan:     str
    cabang:      str
    dimensi_str: str   # "12 x 5 x 10 cm" atau ""


class SparepartInUseItem(BaseModel):
    """Satu baris sparepart — 'Sedang Dipakai' (sparepart_items dari tiket
    servis yang masih Proses/Menunggu_Sparepart) atau 'Riwayat Pemakaian'
    (dari tiket yang baru Selesai, tampil sementara — lihat
    list_sparepart_riwayat). `selesai_pakai` cuma terisi untuk kasus kedua."""
    sp_id:        str
    nama:         str
    kategori:     str = ""
    harga_modal:  int = 0
    jumlah:       int
    service_id:   str
    unit_label:   str
    imei:         str = ""
    teknisi:      str
    mulai_pakai:  Optional[str] = None
    selesai_pakai: Optional[str] = None
    cabang:       str
