import math
import threading
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict, Any

EARTH_RADIUS_KM = 6371.0088

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points on Earth in kilometers."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_KM * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))

def bounding_box_from_circle(lat: float, lon: float, radius_km: float) -> Tuple[float, float, float, float]:
    """
    Computes conservative [min_lat, max_lat, min_lon, max_lon] bounding box
    around (lat, lon) for a given radius_km to enable fast 2-D Tree axis pruning.
    """
    delta_lat = math.degrees(radius_km / EARTH_RADIUS_KM)
    cos_lat = max(math.cos(math.radians(lat)), 1e-6)
    delta_lon = math.degrees(radius_km / (EARTH_RADIUS_KM * cos_lat))
    return (
        max(-90.0, lat - delta_lat),
        min(90.0, lat + delta_lat),
        max(-180.0, lon - delta_lon),
        min(180.0, lon + delta_lon),
    )

@dataclass
class SpatialPoint:
    id: int
    name: str
    cuisine: str
    latitude: float
    longitude: float
    rating: float
    price_tier: int
    address: str

    def to_dict(self, distance_km: Optional[float] = None) -> Dict[str, Any]:
        d = {
            "id": self.id,
            "name": self.name,
            "cuisine": self.cuisine,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "rating": self.rating,
            "price_tier": self.price_tier,
            "address": self.address,
        }
        if distance_km is not None:
            d["distance_km"] = round(distance_km, 4)
        return d

class KDNode:
    __slots__ = ("point", "left", "right", "axis")

    def __init__(
        self,
        point: SpatialPoint,
        axis: int,
        left: Optional["KDNode"] = None,
        right: Optional["KDNode"] = None,
    ):
        self.point = point
        self.axis = axis  # 0 -> latitude, 1 -> longitude
        self.left = left
        self.right = right

class TwoDTreeIndex:
    """
    Thread-safe 2-D Spatial Tree for fast O(sqrt(N) + K) range queries,
    bounding-box pruning, and k-Nearest Neighbor lookups.
    """

    def __init__(self):
        self.root: Optional[KDNode] = None
        self.size: int = 0
        self._points: List[SpatialPoint] = []
        self._lock = threading.RLock()

    def build(self, points: List[SpatialPoint]) -> None:
        """Builds a balanced 2-D Tree using median partitioning."""
        with self._lock:
            self._points = list(points)
            self.size = len(self._points)
            self.root = self._build_recursive(list(self._points), depth=0)

    def _build_recursive(self, pts: List[SpatialPoint], depth: int) -> Optional[KDNode]:
        if not pts:
            return None
        axis = depth % 2
        pts.sort(key=lambda p: p.latitude if axis == 0 else p.longitude)
        mid = len(pts) // 2
        return KDNode(
            point=pts[mid],
            axis=axis,
            left=self._build_recursive(pts[:mid], depth + 1),
            right=self._build_recursive(pts[mid + 1 :], depth + 1),
        )

    def insert(self, point: SpatialPoint) -> None:
        """Dynamically inserts a single restaurant into the 2-D tree."""
        with self._lock:
            self._points.append(point)
            self.size += 1
            if self.root is None:
                self.root = KDNode(point=point, axis=0)
                return
            curr = self.root
            depth = 0
            while True:
                axis = depth % 2
                val = point.latitude if axis == 0 else point.longitude
                curr_val = curr.point.latitude if axis == 0 else curr.point.longitude
                if val < curr_val:
                    if curr.left is None:
                        curr.left = KDNode(point=point, axis=(depth + 1) % 2)
                        break
                    curr = curr.left
                else:
                    if curr.right is None:
                        curr.right = KDNode(point=point, axis=(depth + 1) % 2)
                        break
                    curr = curr.right
                depth += 1

    def query_radius(
        self,
        lat: float,
        lon: float,
        radius_km: float,
        cuisine: Optional[str] = None,
        limit: int = 50,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Executes a circular spatial range query using 2-D Tree bounding-box pruning
        followed by exact Haversine filtering.
        Returns (sorted_results, nodes_visited).
        """
        min_lat, max_lat, min_lon, max_lon = bounding_box_from_circle(lat, lon, radius_km)
        candidates: List[Tuple[float, SpatialPoint]] = []
        nodes_visited = 0
        cuisine_lower = cuisine.lower() if cuisine else None

        def _search(node: Optional[KDNode]):
            nonlocal nodes_visited
            if node is None:
                return
            nodes_visited += 1
            p = node.point

            # Check if current node lies inside the bounding box
            if min_lat <= p.latitude <= max_lat and min_lon <= p.longitude <= max_lon:
                if cuisine_lower is None or p.cuisine.lower() == cuisine_lower:
                    dist = haversine_km(lat, lon, p.latitude, p.longitude)
                    if dist <= radius_km:
                        candidates.append((dist, p))

            # Prune subtrees using splitting hyperplane
            if node.axis == 0:  # Split on latitude
                if min_lat <= p.latitude:
                    _search(node.left)
                if max_lat >= p.latitude:
                    _search(node.right)
            else:  # Split on longitude
                if min_lon <= p.longitude:
                    _search(node.left)
                if max_lon >= p.longitude:
                    _search(node.right)

        with self._lock:
            _search(self.root)

        candidates.sort(key=lambda item: item[0])
        results = [pt.to_dict(distance_km=dist) for dist, pt in candidates[:limit]]
        return results, nodes_visited

    def query_bounding_box(
        self,
        min_lat: float,
        max_lat: float,
        min_lon: float,
        max_lon: float,
        cuisine: Optional[str] = None,
        limit: int = 100,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Executes an orthogonal rectangular range query on the 2-D Tree."""
        matches: List[Dict[str, Any]] = []
        nodes_visited = 0
        cuisine_lower = cuisine.lower() if cuisine else None

        def _search(node: Optional[KDNode]):
            nonlocal nodes_visited
            if node is None or len(matches) >= limit:
                return
            nodes_visited += 1
            p = node.point

            if min_lat <= p.latitude <= max_lat and min_lon <= p.longitude <= max_lon:
                if cuisine_lower is None or p.cuisine.lower() == cuisine_lower:
                    matches.append(p.to_dict())

            if node.axis == 0:
                if min_lat <= p.latitude:
                    _search(node.left)
                if max_lat >= p.latitude:
                    _search(node.right)
            else:
                if min_lon <= p.longitude:
                    _search(node.left)
                if max_lon >= p.longitude:
                    _search(node.right)

        with self._lock:
            _search(self.root)

        return matches, nodes_visited

    def brute_force_radius(
        self,
        lat: float,
        lon: float,
        radius_km: float,
        cuisine: Optional[str] = None,
        limit: int = 50,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Linear O(N) scan baseline used for benchmarking against the 2-D Tree."""
        candidates: List[Tuple[float, SpatialPoint]] = []
        cuisine_lower = cuisine.lower() if cuisine else None
        with self._lock:
            for p in self._points:
                if cuisine_lower and p.cuisine.lower() != cuisine_lower:
                    continue
                dist = haversine_km(lat, lon, p.latitude, p.longitude)
                if dist <= radius_km:
                    candidates.append((dist, p))
            scanned = len(self._points)
        candidates.sort(key=lambda item: item[0])
        return [pt.to_dict(distance_km=dist) for dist, pt in candidates[:limit]], scanned
