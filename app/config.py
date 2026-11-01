import os

class Settings:
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", "postgresql://explorer:explorer_pass@localhost:5432/restaurants_db"
    )
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    KAFKA_BOOTSTRAP_SERVERS: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:29092")
    KAFKA_INGEST_TOPIC: str = os.getenv("KAFKA_INGEST_TOPIC", "restaurant-ingestion-events")
    KAFKA_ANALYTICS_TOPIC: str = os.getenv("KAFKA_ANALYTICS_TOPIC", "spatial-query-analytics")
    L1_CACHE_CAPACITY: int = int(os.getenv("L1_CACHE_CAPACITY", "512"))
    L2_REDIS_TTL_SECONDS: int = int(os.getenv("L2_REDIS_TTL_SECONDS", "600"))
    GRID_PRECISION_DECIMALS: int = int(os.getenv("GRID_PRECISION_DECIMALS", "3"))
    SEED_RESTAURANT_COUNT: int = int(os.getenv("SEED_RESTAURANT_COUNT", "10000"))

settings = Settings()
