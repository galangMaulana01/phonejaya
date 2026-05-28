import asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient
import bcrypt
from dotenv import load_dotenv

load_dotenv()
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB  = os.getenv("MONGO_DB",  "jayapona")


def hash_pw(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


USERS = [
    {"username":"owner",   "password_hash":hash_pw("owner123"),   "name":"Budi Santoso", "role":"owner",   "cabang":"JYP","aktif":True},
    {"username":"andi",    "password_hash":hash_pw("andi123"),     "name":"Andi Rahman",  "role":"kasir",   "cabang":"JYP","aktif":True},
    {"username":"teknisi", "password_hash":hash_pw("teknisi123"),  "name":"Rudi Teknisi", "role":"teknisi", "cabang":"JYP","aktif":True},
]

UNITS = [
    {"unit_id":"JYP-IP-BN-001","merk":"Apple",  "tipe":"iPhone 14 Pro Max","storage":"256GB","warna":"Deep Purple",  "imei":"354823110234567","harga_modal":9500000, "harga_jual":12500000,"kondisi":"Normal",  "battery":88,"status":"Tersedia","kategori":"iPhone", "catatan":"","cabang":"JYP"},
    {"unit_id":"JYP-IP-BN-002","merk":"Apple",  "tipe":"iPhone 13",        "storage":"128GB","warna":"Midnight",    "imei":"354823110298765","harga_modal":6000000, "harga_jual":8200000, "kondisi":"Normal",  "battery":91,"status":"Tersedia","kategori":"iPhone", "catatan":"Lengkap box","cabang":"JYP"},
    {"unit_id":"JYP-AI-BN-003","merk":"Samsung","tipe":"Galaxy S23 Ultra",  "storage":"256GB","warna":"Phantom Black","imei":"352987110123456","harga_modal":8000000, "harga_jual":11000000,"kondisi":"Normal",  "battery":85,"status":"Sold",    "kategori":"Android","catatan":"","cabang":"JYP"},
    {"unit_id":"JYP-AI-MN-004","merk":"Xiaomi", "tipe":"13T Pro",          "storage":"512GB","warna":"Alpine Blue", "imei":"863421110456789","harga_modal":5500000, "harga_jual":7000000, "kondisi":"Minus",   "battery":79,"status":"Tersedia","kategori":"Android","catatan":"Layar ada goresan tipis","cabang":"JYP"},
    {"unit_id":"JYP-IP-EX-005","merk":"Apple",  "tipe":"iPhone 12",        "storage":"64GB", "warna":"Blue",        "imei":"354823110345678","harga_modal":3800000, "harga_jual":5200000, "kondisi":"Ex Inter","battery":82,"status":"Booking", "kategori":"iPhone", "catatan":"HP Ex International","cabang":"JYP"},
    {"unit_id":"JYP-TB-BN-006","merk":"Samsung","tipe":"Galaxy Tab S9",    "storage":"256GB","warna":"Graphite",    "imei":"352987110654321","harga_modal":7200000, "harga_jual":9800000, "kondisi":"Normal",  "battery":95,"status":"Tersedia","kategori":"Tablet", "catatan":"","cabang":"JYP"},
    {"unit_id":"JYP-AI-BN-007","merk":"OPPO",   "tipe":"Find X6 Pro",      "storage":"256GB","warna":"Sepia Brown", "imei":"863421110789012","harga_modal":6500000, "harga_jual":8500000, "kondisi":"Normal",  "battery":90,"status":"Service", "kategori":"Android","catatan":"Sedang service touchscreen","cabang":"JYP"},
]

TRANSAKSI = [
    {"trx_id":"TRX-001","unit_id":"JYP-AI-BN-003","unit_label":"Samsung Galaxy S23 Ultra 256GB","kasir":"Andi Rahman","harga_jual":11000000,"harga_modal":8000000,"profit":3000000,"waktu":datetime(2025,1,15,10,23,tzinfo=timezone.utc),"catatan":"","cabang":"JYP"},
    {"trx_id":"TRX-002","unit_id":"JYP-IP-BN-009","unit_label":"iPhone 14 128GB Midnight",      "kasir":"Andi Rahman","harga_jual":9500000, "harga_modal":7000000,"profit":2500000,"waktu":datetime(2025,1,14,14,45,tzinfo=timezone.utc),"catatan":"","cabang":"JYP"},
    {"trx_id":"TRX-003","unit_id":"JYP-AI-BN-010","unit_label":"Xiaomi 14 Pro 512GB Black",     "kasir":"Andi Rahman","harga_jual":7800000, "harga_modal":5800000,"profit":2000000,"waktu":datetime(2025,1,13, 9,10,tzinfo=timezone.utc),"catatan":"Customer request fast delivery","cabang":"JYP"},
]

KARYAWAN = [
    {"nama":"Andi Rahman",   "username":"andi",    "jabatan":"Kasir",   "cabang":"JYP","gaji":3500000,"aktif":True,"bergabung":"2024-03-01"},
    {"nama":"Siti Nurhaliza","username":"siti",    "jabatan":"Admin",   "cabang":"JYP","gaji":3200000,"aktif":True,"bergabung":"2024-05-15"},
    {"nama":"Rudi Teknisi",  "username":"teknisi", "jabatan":"Teknisi", "cabang":"JYP","gaji":3000000,"aktif":True,"bergabung":"2024-06-01"},
]

SERVICE_DATA = [
    {"service_id":"SVC-001","nama_customer":"Budi Hartono","kontak_customer":"081234567890","merk":"Samsung","tipe":"Galaxy A54","keluhan":"Layar retak","catatan_kerusakan":"LCD pecah bagian kanan","estimasi_biaya":450000,"status":"Proses","teknisi":"Rudi Teknisi","foto_urls":[],"cabang":"JYP","created_at":datetime(2025,1,14,9,0,tzinfo=timezone.utc),"updated_at":datetime(2025,1,14,10,0,tzinfo=timezone.utc)},
    {"service_id":"SVC-002","nama_customer":"Ani Kusuma",  "kontak_customer":"082198765432","merk":"iPhone", "tipe":"13 Pro",     "keluhan":"Baterai cepat habis","catatan_kerusakan":"Battery health 62%","estimasi_biaya":350000,"status":"Masuk","teknisi":"Rudi Teknisi","foto_urls":[],"cabang":"JYP","created_at":datetime(2025,1,15,8,0,tzinfo=timezone.utc),"updated_at":None},
]

CUSTOMERS = [
    {"nama":"Budi Hartono","kontak":"081234567890","cabang":"JYP","created_at":datetime(2025,1,14,9,0,tzinfo=timezone.utc)},
    {"nama":"Ani Kusuma", "kontak":"082198765432","cabang":"JYP","created_at":datetime(2025,1,15,8,0,tzinfo=timezone.utc)},
]

LOG = [
    {"waktu":datetime(2025,1,15,10,23,tzinfo=timezone.utc),"user":"Andi Rahman", "aksi":"Input Transaksi","detail":"TRX-001 • Samsung Galaxy S23 Ultra","cabang":"JYP"},
    {"waktu":datetime(2025,1,15, 9, 0,tzinfo=timezone.utc),"user":"Budi Santoso","aksi":"Tambah Unit",    "detail":"JYP-TB-BN-006 • Galaxy Tab S9",   "cabang":"JYP"},
    {"waktu":datetime(2025,1,14,14,45,tzinfo=timezone.utc),"user":"Andi Rahman", "aksi":"Input Transaksi","detail":"TRX-002 • iPhone 14",              "cabang":"JYP"},
    {"waktu":datetime(2025,1,14, 9, 0,tzinfo=timezone.utc),"user":"Rudi Teknisi","aksi":"Input Service",  "detail":"SVC-001 • Samsung Galaxy A54",     "cabang":"JYP"},
    {"waktu":datetime(2025,1,13, 9,10,tzinfo=timezone.utc),"user":"Andi Rahman", "aksi":"Input Transaksi","detail":"TRX-003 • Xiaomi 14 Pro",           "cabang":"JYP"},
]

COUNTERS = [
    {"_id":"IP","seq":5},{"_id":"AI","seq":7},{"_id":"TB","seq":6},
    {"_id":"AC","seq":0},{"_id":"SP","seq":0},
    {"_id":"TRX","seq":3},{"_id":"SVC","seq":2},
]


async def seed():
    client = AsyncIOMotorClient(MONGO_URI)
    db     = client[MONGO_DB]
    print(f"🌱  Seeding '{MONGO_DB}' ...")

    for col in ["users","units","transaksi","karyawan","service","customers","log","counters"]:
        await db[col].drop()
        print(f"   Dropped '{col}'")

    await db.users.insert_many(USERS);         print(f"   ✅  {len(USERS)} users")
    await db.units.insert_many(UNITS);         print(f"   ✅  {len(UNITS)} units")
    await db.transaksi.insert_many(TRANSAKSI); print(f"   ✅  {len(TRANSAKSI)} transaksi")
    await db.karyawan.insert_many(KARYAWAN);   print(f"   ✅  {len(KARYAWAN)} karyawan")
    await db.service.insert_many(SERVICE_DATA);print(f"   ✅  {len(SERVICE_DATA)} service")
    await db.customers.insert_many(CUSTOMERS); print(f"   ✅  {len(CUSTOMERS)} customers")
    await db.log.insert_many(LOG);             print(f"   ✅  {len(LOG)} log entries")
    await db.counters.insert_many(COUNTERS);   print(f"   ✅  counters seeded")

    # Indexes
    await db.users.create_index("username", unique=True)
    await db.units.create_index("unit_id", unique=True)
    await db.units.create_index("imei")
    await db.units.create_index([("cabang",1),("status",1)])
    await db.transaksi.create_index("trx_id", unique=True)
    await db.transaksi.create_index([("waktu",-1)])
    await db.service.create_index("service_id", unique=True)
    await db.service.create_index([("cabang",1),("status",1)])
    await db.customers.create_index([("cabang",1),("nama",1)])
    await db.log.create_index([("waktu",-1)])
    print("   ✅  indexes created")

    client.close()
    print("\n🎉  Seed selesai!")
    print("   Owner   : owner   / owner123")
    print("   Kasir   : andi    / andi123")
    print("   Teknisi : teknisi / teknisi123")


if __name__ == "__main__":
    asyncio.run(seed())
