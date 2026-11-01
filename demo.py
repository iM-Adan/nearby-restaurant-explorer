"""Small demo for the Nearby Restaurant Explorer spatial search.

Run with:
    python demo.py
"""

from app.kdtree import TwoDTreeIndex, SpatialPoint


def build_demo_restaurants():
    return [
        SpatialPoint(1, "The Royal Table", "North Indian", 28.5458, 77.1928, 4.7, 2, "Near IIT Gate"),
        SpatialPoint(2, "Urban Spice", "North Indian", 28.5491, 77.1953, 4.4, 1, "SDA Market"),
        SpatialPoint(3, "Blue Tokai Cafe", "Cafe & Bakery", 28.5412, 77.1901, 4.8, 2, "Hauz Khas"),
        SpatialPoint(4, "Olive Bistro", "Mediterranean", 28.5526, 77.2015, 4.6, 3, "Near Green Park"),
        SpatialPoint(5, "Zen Grill", "Japanese", 28.5350, 77.1860, 4.5, 3, "Near Saket"),
        SpatialPoint(6, "Masala House", "Street Food", 28.5661, 77.2089, 4.2, 1, "Lajpat Nagar"),
        SpatialPoint(7, "Golden Pizzeria", "Italian", 28.5230, 77.1650, 4.3, 2, "Gurgaon Road"),
    ]


def main():
    tree = TwoDTreeIndex()
    tree.build(build_demo_restaurants())

    lat = 28.5458
    lon = 77.1928
    radius_km = 3.0

    results, nodes_visited = tree.query_radius(lat=lat, lon=lon, radius_km=radius_km, limit=5)
    brute_force_results, _ = tree.brute_force_radius(lat=lat, lon=lon, radius_km=radius_km, limit=5)

    print("Nearby Restaurant Explorer Demo")
    print("=" * 32)
    print(f"Query center: ({lat}, {lon})")
    print(f"Radius: {radius_km} km")
    print(f"KD-tree nodes visited: {nodes_visited}")
    print(f"KD-tree matches: {len(results)}")
    print(f"Brute-force matches: {len(brute_force_results)}")
    print()

    for item in results:
        print(
            f"- {item['name']} ({item['cuisine']}) | "
            f"{item['distance_km']:.2f} km away | rating {item['rating']}"
        )


if __name__ == "__main__":
    main()
