from pydantic import BaseModel, field_validator
from typing import Optional

# Indonesia has 3 timezones, none observing DST.
CABANG_TIMEZONES = {"Asia/Jakarta", "Asia/Makassar", "Asia/Jayapura"}
DEFAULT_CABANG_TIMEZONE = "Asia/Jakarta"


def _validate_timezone(v: Optional[str]) -> Optional[str]:
    if v is not None and v not in CABANG_TIMEZONES:
        raise ValueError(f"Timezone harus salah satu dari: {', '.join(sorted(CABANG_TIMEZONES))}")
    return v


class CabangCreateRequest(BaseModel):
    nama:      str
    kode:      str       # JYP, BN, dll — uppercase
    alamat:    str = ""
    telp:      str = ""
    timezone:  str = DEFAULT_CABANG_TIMEZONE  # zona waktu lokal cabang, dipakai untuk tampilan jam

    @field_validator("nama", "kode")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Tidak boleh kosong")
        if len(v.strip()) > 100:
            raise ValueError("Maksimal 100 karakter")
        return v.strip().upper() if len(v.strip()) <= 5 else v.strip()

    @field_validator("kode")
    @classmethod
    def kode_upper(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("timezone")
    @classmethod
    def timezone_valid(cls, v: str) -> str:
        return _validate_timezone(v)


class CabangUpdateRequest(BaseModel):
    nama:     Optional[str] = None
    alamat:   Optional[str] = None
    telp:     Optional[str] = None
    aktif:    Optional[bool] = None
    timezone: Optional[str] = None

    @field_validator("nama")
    @classmethod
    def nama_length(cls, v: Optional[str]) -> Optional[str]:
        # Sengaja Optional (field ini opsional di PATCH), tapi kalau memang
        # DIKIRIM harus tidak kosong — konfirmasi live: {"nama":""} diterima
        # 200 dan mengosongkan nama cabang di seluruh UI. `None` (field tidak
        # dikirim) tetap harus tetap lolos, cuma string kosong yang ditolak.
        if v is not None:
            if not v.strip():
                raise ValueError("Nama tidak boleh kosong")
            if len(v.strip()) > 100:
                raise ValueError("Maksimal 100 karakter")
        return v

    @field_validator("timezone")
    @classmethod
    def timezone_valid(cls, v: Optional[str]) -> Optional[str]:
        return _validate_timezone(v)


class AssignKepalaCabangRequest(BaseModel):
    username:  str    # username akun yang akan dijadikan kepala cabang
    nama:      str    # nama lengkap
    password:  str    # password login
    foto_profil_url: Optional[str] = None  # foto profil Kepala Cabang

    @field_validator("username", "nama")
    @classmethod
    def not_empty(cls, v: str) -> str:
        # Tidak ada validasi apapun sebelumnya — konfirmasi live:
        # {"username":"", "nama":"Test", "password":"password123"} diterima
        # 200 dan membuat akun users dengan username="" yang tidak bisa login.
        # (password sudah divalidasi minimal 6 karakter di cabang_service.py.)
        if not v.strip():
            raise ValueError("Tidak boleh kosong")
        return v.strip()


class CabangResponse(BaseModel):
    id:              str
    nama:            str
    kode:            str
    alamat:          str
    telp:            str
    aktif:           bool
    timezone:        str = DEFAULT_CABANG_TIMEZONE
    kepala_cabang:   Optional[str] = None   # nama kepala cabang
    kepala_username: Optional[str] = None   # username kepala cabang
    jumlah_karyawan: int = 0
    created_at:      str = ""


class CabangTimezoneItem(BaseModel):
    kode:     str
    timezone: str = DEFAULT_CABANG_TIMEZONE
