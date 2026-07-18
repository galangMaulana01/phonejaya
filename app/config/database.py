import logging
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.config.settings import settings

logger = logging.getLogger(__name__)

_client: AsyncIOMotorClient | None = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(
            settings.MONGO_URI,
            # Timeout settings untuk Vercel serverless
            serverSelectionTimeoutMS=8000,
            connectTimeoutMS=8000,
            socketTimeoutMS=8000,
            # Pool settings minimal untuk serverless (tiap invocation baru)
            maxPoolSize=5,
            minPoolSize=0,
            # Retry otomatis saat connection drop
            retryWrites=True,
            retryReads=True,
            # Tutup idle connection lebih cepat
            maxIdleTimeMS=10000,
            waitQueueTimeoutMS=5000,
        )
        logger.info("MongoDB client created — db: %s", settings.MONGO_DB)
    return _client


def get_db() -> AsyncIOMotorDatabase:
    return get_client()[settings.MONGO_DB]


async def connect_db() -> None:
    client = get_client()
    await client.admin.command("ping")
    logger.info("✅  MongoDB connected — db: %s", settings.MONGO_DB)


async def close_db() -> None:
    global _client
    if _client:
        _client.close()
        _client = None
        logger.info("MongoDB connection closed")


async def init_db() -> None:
    """Create unique indexes for data integrity."""
    client = get_client()
    db = client[settings.MONGO_DB]
    
    # Users collection - unique username
    await db.users.create_index("username", unique=True)
    
    # Karyawan collection - unique username per cabang (or global)
    await db.karyawan.create_index("username", unique=True)
    
    # Cabang collection - unique kode
    await db.cabang.create_index("kode", unique=True)
    
    # Units collection - unique unit_id per cabang
    await db.units.create_index([("unit_id", 1), ("cabang", 1)], unique=True)
    
    # Service collection - unique service_id
    await db.service.create_index("service_id", unique=True)
    
    # Transaksi collection - unique trx_id
    await db.transaksi.create_index("trx_id", unique=True)
    
    # Sparepart collection - unique sp_id
    await db.sparepart.create_index("sp_id", unique=True)
    
    # Influencer videos - unique video_id
    await db.influencer_videos.create_index("video_id", unique=True)
    
    # COD requests - unique cod_id
    await db.cod_requests.create_index("cod_id", unique=True)
    
    # Transfer stok - unique transfer_id
    await db.transfer_stok.create_index("transfer_id", unique=True)
    
    # Request sparepart - unique req_id
    await db.request_sparepart.create_index("req_id", unique=True)
    
    logger.info("Database indexes created/verified")
