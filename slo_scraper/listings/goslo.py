"""goslo.events: static HTML list at /all.

The advertised RSS/Atom feeds are weekly digests of *new* events (not a full
calendar), so the HTML page is the source of truth.
"""
from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup

from ..models import Event
from . import _util as u

URL = "https://goslo.events/all"
SOURCE = "goslo"

# venue (lowercase) -> (display name, town, default category)
VENUES = {
    "slo brew": ("SLO Brew", "San Luis Obispo", "music"),
    "libertine": ("Libertine Brewing", "San Luis Obispo", "music"),
    "the bunker": ("The Bunker", "San Luis Obispo", "other"),
    "madonna inn / expo center": ("Madonna Inn Expo Center", "San Luis Obispo", "festival_market"),
    "central coast roller derby": ("Central Coast Roller Derby", "San Luis Obispo", "other"),
    "vina robles": ("Vina Robles Amphitheatre", "Paso Robles", "music"),
}


def _description(div) -> str:
    text = u.clean(div.get_text(" ")) if div else ""
    text = re.split(r"#block-\S+ \{", text)[0]       # squarespace CSS junk
    text = text.replace("�", "'")
    return text.strip()[:400]


def parse(html_text: str, today=None) -> list[Event]:
    today = today or u.today()
    soup = BeautifulSoup(html_text, "html.parser")
    events: list[Event] = []
    for group in soup.select(".date-group"):
        h2 = group.select_one(".date-title")
        if not h2:
            continue
        try:
            d = datetime.strptime(h2.get_text(strip=True), "%a %b %d %Y").date()
        except ValueError:
            continue
        if d < today:
            continue
        for box in group.select(".event-container"):
            h3 = box.select_one(".event-title")
            if not h3:
                continue
            links = h3.find_all("a")
            if not links:
                continue
            title = u.clean(links[0].get_text()).replace("�", "'")
            url = next((a["href"] for a in links if a.get("href", "").startswith("http")), "")
            venue_raw = u.clean(links[1].get_text()) if len(links) > 1 else ""
            venue, town, default_cat = VENUES.get(
                venue_raw.lower(), (venue_raw, "San Luis Obispo", "other"))
            desc = _description(box.select_one(".event-details"))
            if u.out_of_county(venue_raw, title, desc[:120]):
                continue
            cat = u.guess_category(title, default=default_cat)
            events.append(Event(
                title=title, date=d.isoformat(), category=cat,
                venue=venue, town=town,
                recurring=u.looks_recurring(title) or bool(re.search(
                    r"every (2nd |second |first |1st )?\w*day|monthly|weekly", desc[:250], re.I)),
                description=desc[:300], sources=[url] if url else [URL],
                ticket_url="", source_name=SOURCE, confidence=1.0,
            ))
    return events


def fetch() -> list[Event]:
    return parse(u.fetch_text(URL))
