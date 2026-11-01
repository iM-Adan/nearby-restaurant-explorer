import os
from uuid import uuid4

os.environ["DATABASE_URL"] = "sqlite:///./test_restaurants.db"
os.environ["SEED_RESTAURANT_COUNT"] = "500"

from fastapi.testclient import TestClient
from app.kdtree import TwoDTreeIndex, SpatialPoint
from app.main import app

def test_kdtree_matches_brute_force_exact():
    points = [
        SpatialPoint(1, "Alpha Cafe", "Cafe", 28.5450, 77.1920, 4.5, 2, "IIT Gate"),
        SpatialPoint(2, "Beta Dhaba", "North Indian", 28.5500, 77.1950, 4.2, 1, "SDA"),
        SpatialPoint(3, "Gamma Sushi", "Japanese", 28.6315, 77.2167, 4.8, 4, "CP"),
        SpatialPoint(4, "Delta Pizza", "Italian", 28.5460, 77.1930, 4.1, 2, "Hauz Khas"),
    ]
    tree = TwoDTreeIndex()
    tree.build(points)

    kd_res, visited = tree.query_radius(28.5455, 77.1925, radius_km=2.0)
    bf_res, _ = tree.brute_force_radius(28.5455, 77.1925, radius_km=2.0)

    assert [r["id"] for r in kd_res] == [r["id"] for r in bf_res]
    assert len(kd_res) == 3
    assert visited <= len(points)

def test_api_nearby_and_cache_progression():
    params = {
        "lat": 28.5458,
        "lon": 77.1928,
        "radius_km": 3.0,
        "cuisine": f"test-{uuid4().hex}",
    }

    with TestClient(app) as client:
        # First query -> 2-D Tree compute
        r1 = client.get("/api/v1/restaurants/nearby", params=params)
        assert r1.status_code == 200
        d1 = r1.json()
        assert d1["source_tier"] == "KDTREE_COMPUTE"

        # Second identical query -> L1 In-Memory LRU hit
        r2 = client.get("/api/v1/restaurants/nearby", params=params)
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2["source_tier"] == "L1_MEMORY"
        assert d2["count"] == d1["count"]
