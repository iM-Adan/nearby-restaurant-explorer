from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Index
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime, timezone
from app.config import settings

# Support fallback to SQLite for local unit testing if Postgres is unavailable
connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(settings.DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class RestaurantORM(Base):
    __tablename__ = "restaurants"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    cuisine = Column(String(100), nullable=False, index=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    rating = Column(Float, default=4.0)
    price_tier = Column(Integer, default=2)
    address = Column(String(500), nullable=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("idx_restaurants_lat_lon", "latitude", "longitude"),
    )

class QueryAnalyticsORM(Base):
    __tablename__ = "query_analytics"

    id = Column(Integer, primary_key=True, index=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    radius_km = Column(Float, nullable=False)
    cuisine_filter = Column(String(100), nullable=True)
    cache_tier_hit = Column(String(50), nullable=False) # L1_MEMORY, L2_REDIS, KDTREE_COMPUTE
    execution_time_ms = Column(Float, nullable=False)
    nodes_visited = Column(Integer, default=0)
    result_count = Column(Integer, default=0)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
