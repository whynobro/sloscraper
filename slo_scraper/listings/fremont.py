"""Fremont Theater (San Luis Obispo). Static HTML list at /shows/, tickets on prekindle."""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import Event
from . import _util as u

BASE = "https://fremontslo.com/"
URL = BASE + "shows/"
SOURCE = "fremont"


def _category(title: str) -> str:
    cat = u.guess_category(title, default="music")
    return cat if cat in ("comedy", "film_theater") else "music"


def parse(html_text: str, today=None) -> list[Event]:
    today = today or u.today()
    soup = BeautifulSoup(html_text, "html.parser")
    by_key: dict[tuple[str, str], Event] = {}
    for item in soup.select(".infowrapper"):
        t = item.select_one(".title")
        d = item.select_one(".eventdate .date")
        if not (t and d):
            continue
        try:
            day = datetime.strptime(u.clean(d.get_text()), "%B %d, %Y").date()
        except ValueError:
            continue
        if day < today:
            continue
        title = u.clean(t.get_text())
        times = u.clean(item.select_one(".eventtimes").get_text()) if item.select_one(".eventtimes") else ""
        age = ""
        m = re.search(r",\s*(All Ages|\d{2}\+)\s*$", times)
        if m:
            age, times = m.group(1), times[: m.start()]
        sub = item.select_one(".titlesub")
        performers = []
        if sub:
            s = re.sub(r"^(with|w/)\s*(special guests?|support from|support|guests?)?:?\s*", "",
                       u.clean(sub.get_text()), flags=re.I)
            performers = [p.strip() for p in re.split(r",|&| and ", s) if p.strip()]
        info = urljoin(BASE, "")
        ticket = ""
        for a in item.find_all("a", href=True):
            label = a.get_text(" ", strip=True).lower()
            if "ticket" in label and not ticket:
                ticket = a["href"]
            elif "info" in label:
                info = urljoin(BASE, a["href"])
        key = (day.isoformat(), title.lower())
        if key in by_key:                       # second showing same night
            by_key[key].time += " / " + times
            continue
        by_key[key] = Event(
            title=title, date=day.isoformat(), category=_category(title),
            performers=performers, venue="Fremont Theater", town="San Luis Obispo",
            time=times, ticket_url=ticket, age_limit=age,
            sources=[info if info != BASE else URL], source_name=SOURCE, confidence=1.0,
        )
    return list(by_key.values())


def fetch() -> list[Event]:
    return parse(u.fetch_text(URL))
