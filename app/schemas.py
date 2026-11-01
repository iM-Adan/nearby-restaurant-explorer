from pydantic import BaseModel, Field
from typing import Optional, List

class RestaurantBase(BaseModel):
    name: str = Field(..., example="Spice Route Bistro")
    cuisine: str = Field(..., example="North Indian")
    latitude: float = Field(..., ge=-90.0, le=90.0, example=28.5450)
    longitude: float = Field(..., ge=-180.0, le=180.0, example=77.1926)
    rating: float = Field(default=4.2, ge=0.0, le=5.0)
    price_tier: int = Field(default=2, ge=1, le=4)
    address: Optional[str] = Field(default="Hauz Khas, New Delhi")

class RestaurantCreate(RestaurantBase):
    pass

class RestaurantResult(RestaurantBase):
    id: int
    distance_km: Optional[float] = None

    class Config:
        from_attributes = True

class NearbySearchResponse(BaseModel):
    query_lat: float
    query_lon: float
    radius_km: float
    cuisine_filter: Optional[str] = None
    source_tier: str
    execution_time_ms: float
    kdtree_nodes_visited: int
    total_indexed_restaurants: int
    count: int
    results: List[RestaurantResult]

class BoundingBoxSearchResponse(BaseModel):
    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float
    source_tier: str
    execution_time_ms: float
    kdtree_nodes_visited: int
    count: int
    results: List[RestaurantResult]
