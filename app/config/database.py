import logging
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.config.settings import settings

logger = logging.getLogger(__name__)

# Gunakan global client agar connection di-reuse antar invocation serverless
_client: AsyncIOMotorClient | None = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(
            settings.MONGO_URI,
            serverSelectionTimeoutMS=5000,
            maxPoolSize=10,
            minPoolSize=1,
        )
        logger.info("MongoDB client created — db: %s", settings.MONGO_DB)
    return _client


def get_db() -> AsyncIOMotorDatabase:
    return get_client()[settings.MONGO_DB]


# Untuk lifespan (opsional di serverless)
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
