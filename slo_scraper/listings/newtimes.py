"""SLO New Times community calendar (static HTML, paginated, sorted by date).

Only entries with a parseable schedule are kept:
  "Sun., Oct. 11, 1-4 p.m."          -> dated event
  "Wednesdays, 6 p.m."               -> recurring, next occurrence
  "... Continues through Nov. 1"     -> run (exhibit), start = today, end_date set
"Ongoing" and "second Thursday of every month" style rows are skipped.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from bs4 import BeautifulSoup

from ..models import Event
from . import _util as u

URL = "https://community.newtimesslo.com/sanluisobispo/EventSearch"
SOURCE = "newtimes"
MAX_PAGES = 17

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_DOW = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_MD = re.compile(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})\b")
_TIME = re.compile(r"(\d{1,2}(?::\d{2})?(?:\s*[-–]\s*\d{1,2}(?::\d{2})?)?\s*(?:a\.m\.|p\.m\.|noon))", re.I)


def _md_to_date(mon: str, day: str, today: date) -> date | None:
    try:
        d = date(today.year, _MONTHS[mon[:3].lower()], int(day))
    except (ValueError, KeyError):
        return None
    if d < today - timedelta(days=180):
        d = d.replace(year=d.year + 1)
    return d


def _schedule(sub: str, today: date):
    """Return (start, end, recurring, time) or None."""
    s = u.clean(sub)
    if not s or s.lower().startswith("ongoing") or re.search(r"(first|second|third|fourth|last) \w+ of", s, re.I) \
            or re.search(r"every other", s, re.I):
        return None
    tm = _TIME.search(s)
    time = tm.group(1) if tm else ""
    cont = re.search(r"(?:Continues )?[Tt]hrough\s+(\w+)\.?\s+(\d{1,2})", s)
    end = _md_to_date(cont.group(1), cont.group(2), today) if cont else None
    head = s[: cont.start()] if cont else s
    m = _MD.search(head)
    if m and not re.match(r"^(Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)days?\b", head):
        d = _md_to_date(m.group(1), m.group(2), today)
        if d:
            return d, end if end and end > d else None, False, time
    if cont and not m and re.match(r"^\s*$|^Through", head):
        return today, end, False, time
    dow = re.match(r"^(Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)days?\b", head)
    if dow:
        names = re.findall(r"(Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day", head)
        if "-" in head.split(",")[0]:                    # "Mondays-Fridays": a long run, skip
            return None
        target = _DOW.index(next(n for n in _DOW if n.startswith(names[0].lower())))
        d = today + timedelta(days=(target - today.weekday()) % 7)
        return d, end, True, time
    if cont:
        return today, end, False, time
    return None


def parse(html_text: str, today=None) -> list[Event]:
    today = today or u.today()
    soup = BeautifulSoup(html_text, "html.parser")
    events: list[Event] = []
    for li in soup.select("li.fdn-pres-item"):
        head = li.select_one(".fdn-teaser-headline a")
        sub = li.select_one(".fdn-teaser-subheadline")
        if not (head and sub):
            continue
        sch = _schedule(sub.get_text(" "), today)
        if not sch:
            continue
        start, end, recurring, time = sch
        if start < today:
            continue
        title = u.clean(head.get_text())
        venue_el = li.select_one(".fdn-event-teaser-location-link")
        info = li.select_one(".fdn-teaser-infoline")
        spans = [u.clean(x.get_text()) for x in li.select(".fdn-teaser-infoline span") if "muted" not in " ".join(x.get("class", []))]
        addr = next((x for x in spans if "," in x or re.search(r"\d", x)), "")
        town = u.normalize_town(addr.split(",")[-1]) if "," in addr else ""
        venue = u.clean(venue_el.get_text()) if venue_el else ""
        if u.out_of_county(town, addr, venue, title):
            continue
        if u.is_excluded(title, recurring):
            continue
        tags = [u.clean(a.get_text()) for a in li.select(".fdn-teaser-tag-link")]
        price_el = li.select_one(".fdn-event-teaser-price")
        desc = li.select_one(".fdn-teaser-description")
        blob = f"{title} | {' '.join(tags)}"
        cat = _tag_category(tags, blob)
        events.append(Event(
            title=title, date=start.isoformat(),
            end_date=end.isoformat() if end else None, category=cat,
            venue=venue, town=town, time=time,
            price=u.clean(price_el.get_text()) if price_el else "",
            recurring=recurring or u.looks_recurring(title),
            description=re.sub(r"\(\d{3}\)\s*\d{3}-\d{4}", "", u.clean(desc.get_text()) if desc else "").strip()[:300],
            sources=[head.get("href", URL)], source_name=SOURCE, confidence=1.0,
        ))
    return events


def _tag_category(tags: list[str], blob: str) -> str:
    # screening/film/theatre and comedy keywords beat tags like "Arts"
    title_cat = u.guess_category(blob.split(" | ")[0], default="")
    if title_cat in ("film_theater", "comedy"):
        return title_cat
    t = " ".join(tags).lower()
    if "comedy" in t:
        return "comedy"
    if "music" in t:
        return "music"
    if "film" in t or "theat" in t:
        return "film_theater"
    if "arts" in t or "art" == t.strip():
        return "art"
    if "festival" in t or "market" in t:
        return "festival_market"
    if "food" in t or "drink" in t:
        return "food_drink"
    if "outdoor" in t or "sports" in t:
        return "outdoor"
    if "community" in t or "kids" in t or "culture" in t:
        return "community"
    return u.guess_category(blob)


def fetch() -> list[Event]:
    events: list[Event] = []
    for page in range(1, MAX_PAGES + 1):
        events.extend(parse(u.fetch_text(URL, params={"page": page})))
    seen, out = set(), []
    for e in events:
        if e.key() not in seen:
            seen.add(e.key())
            out.append(e)
    return out
