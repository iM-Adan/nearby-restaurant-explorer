import json
import threading
from collections import OrderedDict
from typing import Optional, Tuple, Any, Dict
from app.config import settings

try:
    import redis
    REDIS_LIB_AVAILABLE = True
except ImportError:
    REDIS_LIB_AVAILABLE = False

class LRUCache:
    """Thread-safe in-memory L1 Least-Recently-Used (LRU) cache."""

    def __init__(self, capacity: int = 512):
        self.capacity = capacity
        self.cache: OrderedDict[str, Any] = OrderedDict()
        self.hits = 0
        self.misses = 0
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key not in self.cache:
                self.misses += 1
                return None
            self.cache.move_to_end(key)
            self.hits += 1
            return self.cache[key]

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            if key in self.cache:
                self.cache.move_to_end(key)
            self.cache[key] = value
            if len(self.cache) > self.capacity:
                self.cache.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self.cache.clear()

    def stats(self) -> Dict[str, int]:
        with self._lock:
            return {
                "size": len(self.cache),
                "capacity": self.capacity,
                "hits": self.hits,
                "misses": self.misses,
            }

class TwoTierSpatialCache:
    """
    Coordinates L1 In-Memory LRU Cache and L2 Redis Distributed Cache.
    Uses quantized spatial grid keys so nearby queries within ~110m share cached entries.
    Includes a serialized JSON L2 fallback store when running offline benchmarks without a live Redis server.
    """

    def __init__(self):
        self.l1 = LRUCache(capacity=settings.L1_CACHE_CAPACITY)
        self.ttl = settings.L2_REDIS_TTL_SECONDS
        self.precision = settings.GRID_PRECISION_DECIMALS
        self.l2_hits = 0
        self.l2_misses = 0
        self._redis: Optional[Any] = None
        self._l2_fallback_store: Dict[str, str] = {}
        self._init_redis()

    def _init_redis(self) -> None:
        if not REDIS_LIB_AVAILABLE:
            return
        try:
            client = redis.Redis.from_url(
                settings.REDIS_URL, decode_responses=True, socket_connect_timeout=1.5
            )
            client.ping()
            self._redis = client
        except Exception:
            self._redis = None

    def make_radius_key(
        self, lat: float, lon: float, radius_km: float, cuisine: Optional[str], limit: int
    ) -> str:
        q_lat = round(lat, self.precision)
        q_lon = round(lon, self.precision)
        q_rad = round(radius_km, 2)
        c_tag = (cuisine or "ALL").lower()
        return f"spatial:radius:{q_lat}:{q_lon}:{q_rad}:{c_tag}:{limit}"

    def make_bbox_key(
        self,
        min_lat: float,
        max_lat: float,
        min_lon: float,
        max_lon: float,
        cuisine: Optional[str],
        limit: int,
    ) -> str:
        c_tag = (cuisine or "ALL").lower()
        return (
            f"spatial:bbox:{round(min_lat, self.precision)}:{round(max_lat, self.precision)}:"
            f"{round(min_lon, self.precision)}:{round(max_lon, self.precision)}:{c_tag}:{limit}"
        )

    def get(self, key: str, bypass_l1: bool = False) -> Tuple[Optional[Any], str]:
        """Returns (cached_payload, tier_name) where tier_name is L1_MEMORY, L2_REDIS, or MISS."""
        if not bypass_l1:
            l1_val = self.l1.get(key)
            if l1_val is not None:
                return l1_val, "L1_MEMORY"

        if self._redis is not None:
            try:
                raw = self._redis.get(key)
                if raw is not None:
                    data = json.loads(raw)
                    self.l2_hits += 1
                    if not bypass_l1:
                        self.l1.put(key, data)
                    return data, "L2_REDIS"
                self.l2_misses += 1
            except Exception:
                pass
        else:
            raw = self._l2_fallback_store.get(key)
            if raw is not None:
                data = json.loads(raw)
                self.l2_hits += 1
                if not bypass_l1:
                    self.l1.put(key, data)
                return data, "L2_REDIS"
            self.l2_misses += 1

        return None, "MISS"

    def set(self, key: str, value: Any) -> None:
        self.l1.put(key, value)
        serialized = json.dumps(value)
        if self._redis is not None:
            try:
                self._redis.setex(key, self.ttl, serialized)
            except Exception:
                pass
        else:
            self._l2_fallback_store[key] = serialized

    def invalidate_all(self) -> None:
        """Purges L1 LRU cache and all spatial:* keys in L2 Redis upon restaurant ingestion."""
        self.l1.clear()
        self._l2_fallback_store.clear()
        if self._redis is not None:
            try:
                keys = self._redis.keys("spatial:*")
                if keys:
                    self._redis.delete(*keys)
            except Exception:
                pass

    def stats(self) -> Dict[str, Any]:
        return {
            "l1_memory": self.l1.stats(),
            "l2_redis": {
                "connected": self._redis is not None,
                "hits": self.l2_hits,
                "misses": self.l2_misses,
                "ttl_seconds": self.ttl,
            },
        }
