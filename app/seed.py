import random
from sqlalchemy.orm import Session
from app.database import RestaurantORM

CUISINES = [
    "North Indian", "South Indian", "Mughlai", "Italian", "Pan-Asian",
    "Japanese", "Continental", "Street Food", "Cafe & Bakery", "Mediterranean"
]

DELHI_HUBS = [
    ("Hauz Khas & IIT Gate", 28.5458, 77.1928),
    ("Connaught Place", 28.6315, 77.2167),
    ("Saket District Centre", 28.5245, 77.2066),
    ("Cyber Hub Gurgaon", 28.4950, 77.0895),
    ("Khan Market", 28.6001, 77.2270),
    ("Vasant Kunj", 28.5293, 77.1532),
    ("Greater Kailash", 28.5482, 77.2345),
    ("Karol Bagh", 28.6514, 77.1907),
    ("Lajpat Nagar", 28.5677, 77.2433),
    ("Noida Sector 18", 28.5708, 77.3260),
]

PREFIXES = [
    "The Royal", "Spice", "Urban", "Golden", "Saffron", "Bistro", "Tandoori",
    "Zen", "Olive", "Masala", "Blue Tokai", "Himalayan", "Old Delhi", "Artisan"
]

SUFFIXES = [
    "Kitchen", "Dhaba", "Courtyard", "Table", "Pavilion", "Roastery",
    "Social", "Grill", "House", "Canteen", "Lounge", "Terrazza"
]

def seed_if_empty(db: Session, target_count: int = 10000) -> int:
    existing = db.query(RestaurantORM).count()
    if existing > 0:
        return existing

    rng = random.Random(42)
    batch = []
    for i in range(1, target_count + 1):
        hub_name, base_lat, base_lon = rng.choice(DELHI_HUBS)
        # Gaussian spatial scatter around major hubs (~1-6 km spread)
        lat = round(base_lat + rng.gauss(0, 0.028), 6)
        lon = round(base_lon + rng.gauss(0, 0.028), 6)
        cuisine = rng.choice(CUISINES)
        name = f"{rng.choice(PREFIXES)} {rng.choice(SUFFIXES)} #{i}"
        rating = round(rng.uniform(3.4, 4.9), 1)
        price_tier = rng.randint(1, 4)
        address = f"Block {rng.randint(1, 25)}, Near {hub_name}, NCR"

        batch.append(
            RestaurantORM(
                name=name,
                cuisine=cuisine,
                latitude=lat,
                longitude=lon,
                rating=rating,
                price_tier=price_tier,
                address=address,
            )
        )
        if len(batch) >= 2000:
            db.bulk_save_objects(batch)
            db.commit()
            batch.clear()

    if batch:
        db.bulk_save_objects(batch)
        db.commit()

    return target_count
