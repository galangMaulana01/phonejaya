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
