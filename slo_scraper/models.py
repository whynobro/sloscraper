"""Shared data contract. Every component reads and writes these types.

Do not change field names without updating all components.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

CATEGORIES = (
    "music",
    "art",
    "festival_market",
    "comedy",
    "film_theater",
    "food_drink",
    "outdoor",
    "community",
    "other",
)

# Canonical town names for SLO County. Sources should map to one of these
# when possible; unknown towns pass through unchanged.
TOWNS = (
    "San Luis Obispo",
    "Morro Bay",
    "Paso Robles",
    "Pismo Beach",
    "Arroyo Grande",
    "Grover Beach",
    "Avila Beach",
    "Los Osos",
    "Cayucos",
    "Cambria",
    "Atascadero",
    "Templeton",
    "Shell Beach",
    "Nipomo",
    "Oceano",
    "Santa Margarita",
)


@dataclass
class Event:
    title: str
    date: str                       # YYYY-MM-DD (local Pacific)
    category: str = "other"         # one of CATEGORIES
    performers: list[str] = field(default_factory=list)
    venue: str = ""
    town: str = ""                  # ideally one of TOWNS
    end_date: Optional[str] = None  # YYYY-MM-DD for multi-day events
    time: str = ""                  # free text, e.g. "7:00 PM" or "Doors 7, show 8"
    price: str = ""                 # free text, e.g. "$25", "Free"
    ticket_url: str = ""
    age_limit: str = ""             # e.g. "21+", "All ages"
    recurring: bool = False         # weekly trivia, farmers market, etc.
    confidence: float = 1.0         # 1.0 for structured listings, model score for IG
    description: str = ""           # short, optional
    sources: list[str] = field(default_factory=list)  # URLs: IG post, listing page
    source_name: str = ""           # e.g. "goslo", "fremont", "ig:fremontslo"
    flyer_path: str = ""            # local path to flyer image, if any

    def key(self) -> str:
        """Stable id within one source: source_name + date + title."""
        return f"{self.source_name}|{self.date}|{self.title.strip().lower()}"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Event":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class Post:
    """One Instagram post as fetched, before extraction."""
    shortcode: str
    account: str
    posted_at: str          # ISO datetime UTC
    caption: str
    url: str                # https://www.instagram.com/p/<shortcode>/
    image_path: str = ""    # local downloaded image (first image / video thumbnail)
