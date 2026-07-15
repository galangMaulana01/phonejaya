from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorDatabase
import logging
import re

logger = logging.getLogger(__name__)

# H5: Log Injection Sanitization
_MAX_USER_LEN = 50
_MAX_AKSI_LEN = 100
_MAX_DETAIL_LEN = 500

_SUSPICIOUS_PATTERNS = [
    r'[\x00-\x1F\x7F]',  # control characters
    r'(?i)(script|eval|alert|onload|onerror)',  # XSS patterns
    r'(\r\n|\r|\n){3,}',  # excessive newlines
]

def _sanitize_log_field(value: str, max_len: int, field_name: str) -> str:
    """Sanitize log field: strip control chars, limit length, reject suspicious patterns."""
    if not isinstance(value, str):
        value = str(value)
    
    # Strip control characters
    value = re.sub(r'[\x00-\x1F\x7F]', '', value)
    
    # Limit length
    if len(value) > max_len:
        value = value[:max_len] + '…'
    
    # Check suspicious patterns
    for pattern in _SUSPICIOUS_PATTERNS:
        if re.search(pattern, value):
            logger.warning(f"Log injection attempt blocked in {field_name}: {value[:100]}")
            return f"[BLOCKED:{field_name}]"
    
    return value


async def write_log(db: AsyncIOMotorDatabase, user: str, aksi: str, detail: str, cabang: str = "") -> None:
    try:
        # H5: Sanitize all fields before storing
        safe_user = _sanitize_log_field(user, _MAX_USER_LEN, "user")
        safe_aksi = _sanitize_log_field(aksi, _MAX_AKSI_LEN, "aksi")
        safe_detail = _sanitize_log_field(detail, _MAX_DETAIL_LEN, "detail")
        safe_cabang = _sanitize_log_field(cabang, 50, "cabang")
        
        await db.log.insert_one({
            "waktu": datetime.now(timezone.utc),
            "user": safe_user,
            "aksi": safe_aksi,
            "detail": safe_detail,
            "cabang": safe_cabang,
        })
    except Exception:
        logger.exception("Gagal menulis log: user=%s aksi=%s", user, aksi)
