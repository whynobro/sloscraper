"""Render events to a single self-contained, phone-friendly HTML page."""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import Event

log = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

CATEGORY_LABELS = {
    "music": "Music",
    "art": "Art",
    "festival_market": "Festivals & Markets",
    "comedy": "Comedy",
    "film_theater": "Film & Theater",
    "food_drink": "Food & Drink",
    "outdoor": "Outdoors",
    "community": "Community",
    "other": "Other",
}

LOW_CONFIDENCE = 0.7
THUMB_MAX_WIDTH = 400
_TIME_RE = re.compile(r"(?<!\d)(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\b", re.I)


def _la_now() -> datetime:
    """Current Pacific time. Falls back to a US DST rule if tzdata is missing
    (fix on Windows: pip install tzdata)."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Los_Angeles"))
    except Exception:
        utc = datetime.now(timezone.utc)
        y = utc.year
        mar = date(y, 3, 1)
        dst_start = mar + timedelta(days=(6 - mar.weekday()) % 7 + 7)  # 2nd Sunday March
        nov = date(y, 11, 1)
        dst_end = nov + timedelta(days=(6 - nov.weekday()) % 7)        # 1st Sunday Nov
        d = (utc - timedelta(hours=8)).date()
        off = -7 if dst_start <= d < dst_end else -8
        return utc.astimezone(timezone(timedelta(hours=off)))


def today_pacific() -> date:
    return _la_now().date()


def _d(s: str) -> date:
    return date.fromisoformat(s)


def _fmt_day(d: date) -> str:
    return f"{d.strftime('%a, %b')} {d.day}"


def _fmt_short(d: date) -> str:
    return f"{d.strftime('%b')} {d.day}"


def parse_time(text: str) -> tuple[int, int] | None:
    """First clock time like '7:00 PM' / '7pm' in free text, else None."""
    m = _TIME_RE.search(text or "")
    if not m:
        return None
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3).lower()
    if not (1 <= h <= 12 and mi < 60):
        return None
    h = h % 12 + (12 if ap == "p" else 0)
    return h, mi


def calendar_url(ev: Event) -> str:
    start = _d(ev.date)
    t = parse_time(ev.time)
    if t:
        s = datetime(start.year, start.month, start.day, t[0], t[1])
        e = s + timedelta(hours=2)
        dates = f"{s:%Y%m%dT%H%M%S}/{e:%Y%m%dT%H%M%S}"
        tz = "&ctz=America%2FLos_Angeles"
    else:
        last = _d(ev.end_date) if ev.end_date else start
        dates = f"{start:%Y%m%d}/{last + timedelta(days=1):%Y%m%d}"
        tz = ""
    details = ev.description or ""
    if ev.sources:
        details = (details + "\n" if details else "") + ev.sources[0]
    location = ", ".join(p for p in (ev.venue, ev.town) if p)
    return (
        "https://calendar.google.com/calendar/render?action=TEMPLATE"
        f"&text={quote(ev.title)}&dates={dates}"
        f"&details={quote(details)}&location={quote(location)}{tz}"
    )


def source_label(url: str) -> str:
    host = (urlparse(url).netloc or url).lower()
    if host.startswith("www."):
        host = host[4:]
    if host == "instagram.com" or host.endswith(".instagram.com"):
        return "Instagram"
    return host or url


def _title_has_performers(ev: Event) -> bool:
    t = ev.title.lower()
    return all(p.lower() in t for p in ev.performers)


def _thumb(flyer_path: str, out_dir: Path) -> str:
    """Write a 400px-wide JPEG thumbnail; return its path relative to site root or ''."""
    try:
        src = Path(flyer_path)
        if not flyer_path or not src.is_file():
            return ""
        from PIL import Image
        name = hashlib.sha1(str(src.resolve()).encode()).hexdigest()[:16] + ".jpg"
        dest_dir = out_dir / "flyers"
        dest_dir.mkdir(parents=True, exist_ok=True)
        with Image.open(src) as im:
            im = im.convert("RGB")
            if im.width > THUMB_MAX_WIDTH:
                h = round(im.height * THUMB_MAX_WIDTH / im.width)
                im = im.resize((THUMB_MAX_WIDTH, max(h, 1)))
            im.save(dest_dir / name, "JPEG", quality=75)
        return f"flyers/{name}"
    except Exception as e:
        log.warning("flyer thumbnail failed for %s: %s", flyer_path, e)
        return ""


LATER_DAYS = 60       # events further out than this are not rendered
OPEN_DAYS = 14        # Later: days within this many days ahead are shown flat, the rest by collapsed week


def is_ongoing(ev: Event, today: date) -> bool:
    """Long runs (exhibits etc): already started and spanning 4+ days, or spanning more than 7 days."""
    if not ev.end_date:
        return False
    start, end = _d(ev.date), _d(ev.end_date)
    span = (end - start).days
    return (start < today and span >= 4) or span > 7


def section_for(ev: Event, today: date) -> str:
    """One of 'today','tomorrow','weekend','week','later','ongoing','recurring'."""
    if ev.recurring:
        return "recurring"
    if is_ongoing(ev, today):
        return "ongoing"
    start = max(_d(ev.date), today)
    if start == today:
        return "today"
    if start == today + timedelta(days=1):
        return "tomorrow"
    sunday = today + timedelta(days=6 - today.weekday())
    wk_start = today if today.weekday() >= 5 else today + timedelta(days=4 - today.weekday())
    if wk_start <= start <= sunday:
        return "weekend"
    if start <= sunday:
        return "week"
    return "later"


def _card(ev: Event, today: date, out_dir: Path) -> dict:
    start, end = _d(ev.date), (_d(ev.end_date) if ev.end_date else None)
    multi = end is not None and end > start
    show_performers = bool(ev.performers) and not _title_has_performers(ev)
    return {
        "title": ev.title,
        "performers": ", ".join(ev.performers) if show_performers else "",
        "category": ev.category,
        "category_label": CATEGORY_LABELS.get(ev.category, "Other"),
        "venue": ev.venue,
        "town": ev.town,
        "time": ev.time,
        "price": ev.price,
        "age_limit": ev.age_limit,
        "date_range": f"{_fmt_short(start)} to {_fmt_short(end)}" if multi else "",
        "ticket_url": ev.ticket_url,
        "links": [{"url": u, "label": source_label(u)} for u in ev.sources if u],
        "cal_url": calendar_url(ev),
        "low_confidence": ev.confidence < LOW_CONFIDENCE,
        "flyer": _thumb(ev.flyer_path, out_dir) if ev.flyer_path else "",
        "sort": (max(start, today).isoformat(), ev.time, ev.title.lower()),
        "day": max(start, today),
    }


SECTION_ORDER = ("today", "tomorrow", "weekend", "week", "later", "ongoing", "recurring")
SECTION_TITLES = {"today": "Today", "tomorrow": "Tomorrow", "weekend": "This weekend",
                  "week": "Rest of this week", "later": "Later", "ongoing": "Ongoing exhibits & runs",
                  "recurring": "Recurring"}


def _group_days(cards: list[dict]) -> list[dict]:
    days: list[dict] = []
    for c in cards:
        if not days or days[-1]["date"] != c["day"]:
            days.append({"date": c["day"], "label": _fmt_day(c["day"]), "cards": []})
        days[-1]["cards"].append(c)
    return days


def build_sections(events: list[Event], today: date, out_dir: Path) -> list[dict]:
    buckets: dict[str, list[dict]] = {k: [] for k in SECTION_ORDER}
    horizon = today + timedelta(days=LATER_DAYS)
    for ev in events:
        last = _d(ev.end_date) if ev.end_date else _d(ev.date)
        if max(_d(ev.date), last) < today:
            continue
        key = section_for(ev, today)
        if key == "later" and _d(ev.date) > horizon:
            continue
        buckets[key].append(_card(ev, today, out_dir))
    out = []
    for key in SECTION_ORDER:
        cards = sorted(buckets[key], key=lambda c: c["sort"])
        sec = {"key": key, "title": SECTION_TITLES[key], "count": len(cards),
               "collapsed": key in ("ongoing", "recurring"), "days": [], "weeks": []}
        if key == "later":
            cut = today + timedelta(days=OPEN_DAYS)
            sec["days"] = _group_days([c for c in cards if c["day"] <= cut])
            weeks: dict[date, list[dict]] = {}
            for c in cards:
                if c["day"] > cut:
                    weeks.setdefault(c["day"] - timedelta(days=c["day"].weekday()), []).append(c)
            sec["weeks"] = [{"label": f"Week of {_fmt_short(w)}", "count": len(cs), "days": _group_days(cs)}
                            for w, cs in sorted(weeks.items())]
        else:
            sec["days"] = _group_days(cards)
        out.append(sec)
    return out


def render(events: list[Event], out_dir: str | Path = "site", generated_at: datetime | None = None,
           source_stats: dict | None = None, today: date | str | None = None) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if today is None:
        today = today_pacific()
    elif isinstance(today, str):
        today = _d(today)
    if generated_at is None:
        generated_at = datetime.now(timezone.utc)
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)

    sections = build_sections(events, today, out)
    total = sum(s["count"] for s in sections)
    all_cards = [c for s in sections for d in s["days"] for c in d["cards"]]
    towns = sorted({c["town"] for c in all_cards if c["town"]})
    cats = [(k, v) for k, v in CATEGORY_LABELS.items() if any(c["category"] == k for c in all_cards)]
    stats = [{"source": k, "events": v.get("events", 0), "unique": v.get("unique", ""),
              "error": v.get("error") or ""} for k, v in sorted((source_stats or {}).items())]

    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)),
                      autoescape=select_autoescape(["html", "j2"], default=True))
    html = env.get_template("index.html.j2").render(
        sections=sections, total=total, towns=towns, categories=cats, stats=stats,
        generated_iso=generated_at.astimezone(timezone.utc).isoformat(timespec="seconds"),
        today_label=_fmt_day(today),
    )
    path = out / "index.html"
    path.write_text(html, encoding="utf-8")
    return path
