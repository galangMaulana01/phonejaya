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
            # Timeout settings untuk Vercel serverless — diperpanjang untuk cold start
            serverSelectionTimeoutMS=30000,
            connectTimeoutMS=30000,
            socketTimeoutMS=30000,
            # Pool settings minimal untuk serverless (tiap invocation baru)
            maxPoolSize=5,
            minPoolSize=0,
            # Retry otomatis saat connection drop
            retryWrites=True,
            retryReads=True,
            # Tutup idle connection lebih cepat
            maxIdleTimeMS=30000,
            waitQueueTimeoutMS=10000,
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
    """Create unique indexes for data integrity.

    Each index is created independently (own try/except) — this used to be
    one straight-line sequence of awaits, which meant a single failure (e.g.
    a unique index that can't build because duplicate values already exist
    in that collection) raised out of init_db() and silently skipped EVERY
    remaining index in the list, since app.main's startup warmup wraps the
    whole call in a blanket try/except that only logs a warning. A multi-role
    audit caught this: one dirty collection quietly left several unrelated
    uniqueness guarantees (req_id, cod_id, transfer_id, customers) never
    enforced. Now a bad collection only costs its own index."""
    client = get_client()
    db = client[settings.MONGO_DB]

    index_specs = [
        ("users", "username", {"unique": True}),
        ("karyawan", "username", {"unique": True}),
        ("cabang", "kode", {"unique": True}),
        ("units", [("unit_id", 1), ("cabang", 1)], {"unique": True}),
        ("service", "service_id", {"unique": True}),
        ("transaksi", "trx_id", {"unique": True}),
        ("sparepart", "sp_id", {"unique": True}),
        ("influencer_videos", "video_id", {"unique": True}),
        ("cod_requests", "cod_id", {"unique": True}),
        ("transfer_stok", "transfer_id", {"unique": True}),
        ("request_sparepart", "req_id", {"unique": True}),
        ("customers", [("kontak", 1), ("cabang", 1)], {"unique": True}),
    ]

    failures = []
    for collection_name, keys, options in index_specs:
        try:
            await db[collection_name].create_index(keys, **options)
        except Exception as e:
            failures.append(collection_name)
            logger.error("Failed to create index on %s (%s): %s", collection_name, keys, e)

    if failures:
        logger.warning("Database indexes created with %d failure(s): %s", len(failures), ", ".join(failures))
    else:
        logger.info("Database indexes created/verified")
