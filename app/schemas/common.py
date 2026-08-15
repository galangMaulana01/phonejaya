from typing import Any, Optional

# Shared upper bound for any rupiah/quantity-style integer field across
# schemas. Without SOME ceiling, a typo with an extra digit (or a
# deliberately huge value) sails past a ">0"/">=0" validator and hits Mongo's
# BSON int64 boundary downstream, which raises an unhandled 500 instead of a
# clean 422 — confirmed live during a multi-role audit (POST /karyawan with
# gaji=9223372036854775808, POST /units with an equally large harga_jual).
# A trillion rupiah is already absurd for this shop's real numbers, so this
# is not a meaningful business constraint — it exists purely to keep bad
# input inside a range Mongo/BSON can represent.
MAX_RUPIAH = 999_999_999_999


def ok(data: Any = None, message: str = "OK") -> dict:
    return {"success": True, "message": message, "data": data}


def err(message: str) -> dict:
    return {"success": False, "message": message, "data": None}
