import time
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, Depends, Query, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import Base, engine, SessionLocal, get_db, RestaurantORM, QueryAnalyticsORM
from app.schemas import (
    RestaurantCreate,
    RestaurantResult,
    NearbySearchResponse,
    BoundingBoxSearchResponse,
)
from app.kdtree import TwoDTreeIndex, SpatialPoint
from app.cache import TwoTierSpatialCache
from app.kafka_bus import AsyncKafkaManager
from app.seed import seed_if_empty

spatial_tree = TwoDTreeIndex()
spatial_cache = TwoTierSpatialCache()

def reload_tree_from_db(db: Session) -> int:
    rows = db.query(RestaurantORM).all()
    points = [
        SpatialPoint(
            id=r.id,
            name=r.name,
            cuisine=r.cuisine,
            latitude=r.latitude,
            longitude=r.longitude,
            rating=r.rating,
            price_tier=r.price_tier,
            address=r.address or "",
        )
        for r in rows
    ]
    spatial_tree.build(points)
    return len(points)

def handle_kafka_restaurant_ingest(payload: Dict[str, Any]) -> None:
    """Kafka consumer callback: persists new restaurant, updates 2-D Tree, and invalidates caches."""
    db = SessionLocal()
    try:
        new_rest = RestaurantORM(
            name=payload["name"],
            cuisine=payload["cuisine"],
            latitude=float(payload["latitude"]),
            longitude=float(payload["longitude"]),
            rating=float(payload.get("rating", 4.2)),
            price_tier=int(payload.get("price_tier", 2)),
            address=payload.get("address", ""),
        )
        db.add(new_rest)
        db.commit()
        db.refresh(new_rest)

        spatial_tree.insert(
            SpatialPoint(
                id=new_rest.id,
                name=new_rest.name,
                cuisine=new_rest.cuisine,
                latitude=new_rest.latitude,
                longitude=new_rest.longitude,
                rating=new_rest.rating,
                price_tier=new_rest.price_tier,
                address=new_rest.address or "",
            )
        )
        spatial_cache.invalidate_all()
    finally:
        db.close()

def handle_kafka_analytics_log(metrics: Dict[str, Any]) -> None:
    """Kafka consumer callback: asynchronously records query execution telemetry in DB."""
    db = SessionLocal()
    try:
        entry = QueryAnalyticsORM(
            latitude=metrics["latitude"],
            longitude=metrics["longitude"],
            radius_km=metrics["radius_km"],
            cuisine_filter=metrics.get("cuisine_filter"),
            cache_tier_hit=metrics["cache_tier_hit"],
            execution_time_ms=metrics["execution_time_ms"],
            nodes_visited=metrics.get("nodes_visited", 0),
            result_count=metrics.get("result_count", 0),
        )
        db.add(entry)
        db.commit()
    finally:
        db.close()

kafka_manager = AsyncKafkaManager(
    on_restaurant_ingested=handle_kafka_restaurant_ingest,
    on_analytics_logged=handle_kafka_analytics_log,
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_if_empty(db, target_count=settings.SEED_RESTAURANT_COUNT)
        reload_tree_from_db(db)
    finally:
        db.close()
    kafka_manager.start()
    yield
    kafka_manager.stop()

app = FastAPI(
    title="Nearby Restaurant Explorer API",
    description=(
        "High-performance location-based restaurant discovery system powered by a custom 2-D Spatial Tree, "
        "Two-Tier L1/L2 (In-Memory LRU + Redis) Caching, and Apache Kafka asynchronous event pipelines."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", include_in_schema=False)
def serve_map_ui():
    return FileResponse("static/index.html")

@app.get("/api/v1/restaurants/nearby", response_model=NearbySearchResponse)
def search_nearby_restaurants(
    lat: float = Query(..., ge=-90.0, le=90.0, description="Query latitude"),
    lon: float = Query(..., ge=-180.0, le=180.0, description="Query longitude"),
    radius_km: float = Query(3.0, gt=0.0, le=100.0, description="Search radius in km"),
    cuisine: Optional[str] = Query(None, description="Optional cuisine filter"),
    limit: int = Query(50, ge=1, le=500, description="Max results"),
    mode: str = Query(
        "default",
        description="Execution mode: 'default' (L1->L2->2DTree), 'l2_only' (bypass L1), 'kdtree_only' (bypass cache), or 'brute_force' (O(N) scan)",
    ),
):
    t0 = time.perf_counter()
    cache_key = spatial_cache.make_radius_key(lat, lon, radius_km, cuisine, limit)
    nodes_visited = 0
    source_tier = "KDTREE_COMPUTE"
    results: Optional[List[Dict[str, Any]]] = None

    if mode in ("default", "l2_only"):
        cached_payload, tier = spatial_cache.get(cache_key, bypass_l1=(mode == "l2_only"))
        if cached_payload is not None:
            results = cached_payload["results"]
            nodes_visited = cached_payload["nodes_visited"]
            source_tier = tier

    if results is None:
        if mode == "brute_force":
            results, nodes_visited = spatial_tree.brute_force_radius(
                lat=lat, lon=lon, radius_km=radius_km, cuisine=cuisine, limit=limit
            )
            source_tier = "BRUTE_FORCE_SCAN"
        else:
            results, nodes_visited = spatial_tree.query_radius(
                lat=lat, lon=lon, radius_km=radius_km, cuisine=cuisine, limit=limit
            )
            source_tier = "KDTREE_COMPUTE"
            if mode == "default":
                spatial_cache.set(
                    cache_key, {"results": results, "nodes_visited": nodes_visited}
                )

    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 4)

    # Publish non-blocking telemetry event to Kafka
    kafka_manager.publish_search_analytics(
        {
            "latitude": lat,
            "longitude": lon,
            "radius_km": radius_km,
            "cuisine_filter": cuisine,
            "cache_tier_hit": source_tier,
            "execution_time_ms": elapsed_ms,
            "nodes_visited": nodes_visited,
            "result_count": len(results),
        }
    )

    return NearbySearchResponse(
        query_lat=lat,
        query_lon=lon,
        radius_km=radius_km,
        cuisine_filter=cuisine,
        source_tier=source_tier,
        execution_time_ms=elapsed_ms,
        kdtree_nodes_visited=nodes_visited,
        total_indexed_restaurants=spatial_tree.size,
        count=len(results),
        results=results,
    )

@app.get("/api/v1/restaurants/bbox", response_model=BoundingBoxSearchResponse)
def search_bounding_box(
    min_lat: float = Query(..., ge=-90.0, le=90.0),
    max_lat: float = Query(..., ge=-90.0, le=90.0),
    min_lon: float = Query(..., ge=-180.0, le=180.0),
    max_lon: float = Query(..., ge=-180.0, le=180.0),
    cuisine: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    if min_lat > max_lat or min_lon > max_lon:
        raise HTTPException(status_code=400, detail="Invalid bounding box bounds.")

    t0 = time.perf_counter()
    cache_key = spatial_cache.make_bbox_key(min_lat, max_lat, min_lon, max_lon, cuisine, limit)
    cached_payload, tier = spatial_cache.get(cache_key)

    if cached_payload is not None:
        results = cached_payload["results"]
        nodes_visited = cached_payload["nodes_visited"]
        source_tier = tier
    else:
        results, nodes_visited = spatial_tree.query_bounding_box(
            min_lat=min_lat,
            max_lat=max_lat,
            min_lon=min_lon,
            max_lon=max_lon,
            cuisine=cuisine,
            limit=limit,
        )
        source_tier = "KDTREE_COMPUTE"
        spatial_cache.set(cache_key, {"results": results, "nodes_visited": nodes_visited})

    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 4)
    return BoundingBoxSearchResponse(
        min_lat=min_lat,
        max_lat=max_lat,
        min_lon=min_lon,
        max_lon=max_lon,
        source_tier=source_tier,
        execution_time_ms=elapsed_ms,
        kdtree_nodes_visited=nodes_visited,
        count=len(results),
        results=results,
    )

@app.post("/api/v1/restaurants", status_code=202)
def ingest_restaurant_async(restaurant: RestaurantCreate):
    """
    Publishes a restaurant creation event to Kafka for asynchronous persistence,
    live 2-D tree insertion, and L1/L2 cache invalidation.
    """
    dispatch_mode = kafka_manager.publish_restaurant_ingestion(restaurant.model_dump())
    return {
        "status": "accepted",
        "dispatch_mode": dispatch_mode,
        "message": "Restaurant queued for asynchronous ingestion, 2-D tree indexing, and cache invalidation.",
        "payload": restaurant.model_dump(),
    }

@app.post("/api/v1/index/rebuild")
def force_rebuild_index(db: Session = Depends(get_db)):
    t0 = time.perf_counter()
    total = reload_tree_from_db(db)
    spatial_cache.invalidate_all()
    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
    return {
        "status": "rebuilt",
        "indexed_restaurants": total,
        "rebuild_time_ms": elapsed_ms,
    }

@app.get("/api/v1/stats")
def system_telemetry(db: Session = Depends(get_db)):
    recent_queries = (
        db.query(QueryAnalyticsORM)
        .order_by(QueryAnalyticsORM.id.desc())
        .limit(15)
        .all()
    )
    return {
        "spatial_index": {
            "algorithm": "2-D Spatial Tree (Balanced Median Split + Haversine Pruning)",
            "indexed_points": spatial_tree.size,
        },
        "cache": spatial_cache.stats(),
        "kafka": {
            "broker_connected": kafka_manager.connected,
            "published_events": kafka_manager.published_events,
            "consumed_events": kafka_manager.consumed_events,
        },
        "recent_analytics": [
            {
                "lat": q.latitude,
                "lon": q.longitude,
                "radius_km": q.radius_km,
                "tier": q.cache_tier_hit,
                "latency_ms": q.execution_time_ms,
                "nodes_visited": q.nodes_visited,
                "results": q.result_count,
            }
            for q in recent_queries
        ],
    }
