import time
import random
import statistics
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.kdtree import TwoDTreeIndex, SpatialPoint
from app.cache import TwoTierSpatialCache

def generate_synthetic_points(n: int = 10000) -> list[SpatialPoint]:
    rng = random.Random(2026)
    cuisines = ["North Indian", "South Indian", "Italian", "Japanese", "Pan-Asian"]
    points = []
    for i in range(1, n + 1):
        lat = 28.5458 + rng.uniform(-0.25, 0.25)
        lon = 77.1928 + rng.uniform(-0.25, 0.25)
        points.append(
            SpatialPoint(
                id=i,
                name=f"Restaurant #{i}",
                cuisine=rng.choice(cuisines),
                latitude=lat,
                longitude=lon,
                rating=4.3,
                price_tier=2,
                address="New Delhi",
            )
        )
    return points

def run_benchmark(num_points: int = 10000, num_queries: int = 200):
    print(f"Building 2-D Spatial Tree with {num_points:,} restaurants...")
    points = generate_synthetic_points(num_points)
    tree = TwoDTreeIndex()
    t_build_start = time.perf_counter()
    tree.build(points)
    build_ms = (time.perf_counter() - t_build_start) * 1000.0
    print(f"2-D Tree built in {build_ms:.2f} ms.\n")

    cache = TwoTierSpatialCache()
    rng = random.Random(99)
    queries = [
        (28.5458 + rng.uniform(-0.1, 0.1), 77.1928 + rng.uniform(-0.1, 0.1), 2.5)
        for _ in range(num_queries)
    ]

    bf_times, kd_times, l2_times, l1_times = [], [], [], []
    kd_nodes_visited = []

    for lat, lon, rad in queries:
        # 1. Brute-Force O(N) Scan
        t0 = time.perf_counter()
        tree.brute_force_radius(lat, lon, rad)
        bf_times.append((time.perf_counter() - t0) * 1000.0)

        # 2. 2-D Tree Range Search (Cold)
        t0 = time.perf_counter()
        res, visited = tree.query_radius(lat, lon, rad)
        kd_times.append((time.perf_counter() - t0) * 1000.0)
        kd_nodes_visited.append(visited)

        # Populate cache
        key = cache.make_radius_key(lat, lon, rad, None, 50)
        cache.set(key, {"results": res, "nodes_visited": visited})

        # 3. L2 Redis Lookup (if connected) or simulated JSON deserialization
        t0 = time.perf_counter()
        cache.get(key, bypass_l1=True)
        l2_times.append((time.perf_counter() - t0) * 1000.0)

        # 4. L1 In-Memory LRU Lookup
        t0 = time.perf_counter()
        cache.get(key, bypass_l1=False)
        l1_times.append((time.perf_counter() - t0) * 1000.0)

    avg_nodes = statistics.mean(kd_nodes_visited)
    pruned_pct = (1.0 - avg_nodes / num_points) * 100.0

    print("=" * 78)
    print(f"{'Execution Tier':<28} | {'Mean (ms)':<10} | {'P95 (ms)':<10} | {'Speedup vs Brute'}")
    print("-" * 78)
    bf_mean = statistics.mean(bf_times)
    for label, samples in [
        ("Brute-Force O(N) Scan", bf_times),
        ("2-D Tree Spatial Search", kd_times),
        ("L2 Redis Cache", l2_times),
        ("L1 In-Memory LRU Cache", l1_times),
    ]:
        mean_v = statistics.mean(samples)
        p95_v = sorted(samples)[int(0.95 * len(samples))]
        speedup = bf_mean / max(mean_v, 1e-6)
        print(f"{label:<28} | {mean_v:<10.4f} | {p95_v:<10.4f} | {speedup:,.1f}x")
    print("=" * 78)
    print(f"Average 2-D Tree Nodes Visited: {avg_nodes:.1f} / {num_points:,} ({pruned_pct:.1f}% search space pruned)")

if __name__ == "__main__":
    run_benchmark()
