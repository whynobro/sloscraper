"""Hello Morro Bay (WordPress + The Events Calendar). Uses the Tribe REST API.

The calendar lists daily repeating items (Dockside lunch sets, exhibits, movie
showings). Series with 3+ occurrences are collapsed into one recurring Event
(first date .. last date); same-day duplicates (matinee/evening) are merged.
"""
from __future__ import annotations

import json
import re
from datetime import timedelta

from ..models import Event
from . import _util as u

API = "https://hellomorrobay.com/wp-json/tribe/events/v1/events"
SOURCE = "hellomorrobay"
WINDOW_DAYS = 75
MAX_PAGES = 8

_CAT_MAP = (  # (tribe category name lowercase, our category), priority order
    ("comedy", "comedy"), ("live music", "music"), ("movie time", "film_theater"),
    ("art & culture", "art"), ("markets & shopping", "festival_market"),
    ("festivals", "festival_market"), ("festival", "festival_market"),
    ("outdoor", "outdoor"), ("outdoors & recreation", "outdoor"),
    ("food & drink", "food_drink"), ("family", "community"), ("community", "community"),
)


def _category(cats: list[str], title: str) -> str:
    low = [c.lower() for c in cats]
    for name, ours in _CAT_MAP:
        if name in low:
            return ours
    return u.guess_category(title, default="other")


def _to_event(e: dict) -> Event | None:
    title = u.clean(e.get("title", ""))
    title = re.sub(r"^Nearby:\s*", "", title)
    title = re.sub(r"\s*\((?:matinee|evening|afternoon|late)[^)]*\)", "", title)
    venue_d = e.get("venue") if isinstance(e.get("venue"), dict) else {}
    venue = u.clean(venue_d.get("venue", ""))
    city = venue_d.get("city", "")
    if u.out_of_county(city, title, venue):
        return None
    if u.is_excluded(title):
        return None
    cats = [u.clean(c.get("name", "")) for c in e.get("categories", [])]
    start = e["start_date"]
    day, hhmm = start[:10], start[11:16]
    h = int(hhmm[:2]) if hhmm else 0
    time = "" if e.get("all_day") else f"{(h % 12) or 12}:{hhmm[3:5]} {'AM' if h < 12 else 'PM'}"
    performers = []
    m = re.match(r"^(?:Live Music|Live):\s*(.+?)\s+(?:at|@)\s+", title, re.I)
    if m and not re.search(r"lunch sets|afternoon sets|open mic", m.group(1), re.I):
        performers = [m.group(1)]
    cost = u.clean(e.get("cost", ""))
    return Event(
        title=title, date=day, category=_category(cats, title), performers=performers,
        venue=venue, town=u.normalize_town(city) or "Morro Bay",
        end_date=None, time=time, price=cost,
        ticket_url=e.get("website", "") or "",
        recurring=u.looks_recurring(title),
        description=u.clean(re.sub(r"<[^>]+>", " ", e.get("excerpt", "")))[:300],
        sources=[e.get("url", "")] if e.get("url") else ["https://hellomorrobay.com/events/"],
        source_name=SOURCE, confidence=1.0,
    )


def _collapse(events: list[Event]) -> list[Event]:
    """Merge same-day duplicates, then collapse 3+ occurrence series."""
    same_day: dict[tuple, Event] = {}
    for ev in events:
        k = (ev.title.lower(), ev.venue.lower(), ev.date)
        if k in same_day:
            if ev.time and ev.time not in same_day[k].time:
                same_day[k].time += " / " + ev.time
        else:
            same_day[k] = ev
    series: dict[tuple, list[Event]] = {}
    for ev in same_day.values():
        series.setdefault((re.sub(r"\(.*?\)", "", ev.title.lower()).strip(), ev.venue.lower()), []).append(ev)
    out: list[Event] = []
    for evs in series.values():
        evs.sort(key=lambda x: x.date)
        if len(evs) >= 3:
            first = evs[0]
            first.end_date = evs[-1].date
            first.recurring = first.category != "art"   # exhibits are runs, not recurring
            out.append(first)
        else:
            out.extend(evs)
    return sorted(out, key=lambda x: (x.date, x.title))


def parse(json_text: str, today=None) -> list[Event]:
    """Parse one REST response page (or a concatenation dict with 'events')."""
    today = today or u.today()
    data = json.loads(json_text)
    raw = data["events"] if isinstance(data, dict) else data
    events = []
    for e in raw:
        ev = _to_event(e)
        if ev and ev.date >= today.isoformat():
            events.append(ev)
    return _collapse(events)


def fetch() -> list[Event]:
    start = u.today()
    params = {"per_page": 50, "start_date": start.isoformat(),
              "end_date": (start + timedelta(days=WINDOW_DAYS)).isoformat()}
    raw: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        r = u.http_get(API, params={**params, "page": page})
        d = r.json()
        raw.extend(d.get("events", []))
        if page >= d.get("total_pages", 1):
            break
    return parse(json.dumps({"events": raw}))
