from datetime import date
from pathlib import Path

from slo_scraper.listings import SOURCES, fetch_all, fremont, goslo, hellomorrobay, newtimes
from slo_scraper.models import CATEGORIES, TOWNS, Event

FIX = Path(__file__).parent / "fixtures"
TODAY = date(2026, 10, 5)


def read(name):
    return (FIX / name).read_text(encoding="utf-8", errors="replace")


def check_common(events, source):
    assert events
    for e in events:
        assert isinstance(e, Event)
        assert e.source_name == source
        assert e.category in CATEGORIES
        assert e.confidence == 1.0 and e.sources and e.sources[0].startswith("http")
        assert len(e.date) == 10 and e.date >= TODAY.isoformat()
        assert e.title


def test_goslo():
    ev = goslo.parse(read("goslo_all.html"), today=TODAY)
    check_common(ev, "goslo")
    assert len(ev) >= 40
    vina = [e for e in ev if e.title == "Slightly Stoopid"][0]
    assert vina.town == "Paso Robles" and vina.category == "music" and vina.date == "2026-10-08"
    assert any(e.category == "comedy" for e in ev)
    assert any(e.title == "Karaoke" and e.recurring for e in ev)
    assert all(e.town in TOWNS for e in ev)
    assert "#block-" not in " ".join(e.description for e in ev)


def test_goslo_drops_past_and_out_of_county():
    ev = goslo.parse(read("goslo_all.html"), today=date(2026, 11, 1))
    assert min(e.date for e in ev) >= "2026-11-01"
    html = ('<div class="date-group"><h2 class="date-title">Sat Oct 10 2026</h2>'
            '<div class="event-container"><div><h3 class="event-title"><a href="http://x/e">Rodeo</a> at '
            '<a href="http://x">Carson City Arena</a></h3><div class="event-details">d</div></div></div></div>')
    assert goslo.parse(html, today=TODAY) == []


def test_fremont():
    ev = fremont.parse(read("fremont_shows.html"), today=TODAY)
    check_common(ev, "fremont")
    first = ev[0]
    assert first.title.startswith("LUKAS NELSON") and first.date == "2026-10-05"
    assert first.venue == "Fremont Theater" and first.town == "San Luis Obispo"
    assert first.age_limit == "All Ages" and first.time == "Doors 7:00 PM / Show 8:00 PM"
    assert first.ticket_url.startswith("https://www.prekindle.com/")
    assert any(e.date == "2026-10-06" and e.title.startswith("Michelle Branch") for e in ev)
    assert any(e.category == "comedy" for e in ev)
    # two showings same night merge into one event
    rocky = [e for e in ev if "Rocky Horror" in e.title]
    assert len(rocky) == 1 and " / " in rocky[0].time and rocky[0].category == "film_theater"
    assert len({e.key() for e in ev}) == len(ev)


def test_hellomorrobay():
    ev = hellomorrobay.parse(read("hellomorrobay_events.json"), today=TODAY)
    check_common(ev, "hellomorrobay")
    siren = [e for e in ev if e.venue == "The Siren" and "D.R.I." in e.title][0]
    assert siren.category == "music" and siren.town == "Morro Bay" and siren.price == "$25"
    assert siren.performers and siren.time == "6:30 PM"
    # daily series collapsed into one recurring event with an end_date
    dock = [e for e in ev if "Lunch Sets at Dockside Too" in e.title]
    assert len(dock) == 1 and dock[0].recurring and dock[0].end_date
    assert any(e.town == "Cayucos" and "Nearby" not in e.title for e in ev)
    assert not any("\U0001f3b6" in e.title for e in ev)
    assert any(e.category == "film_theater" for e in ev)
    assert any(e.category == "festival_market" and e.recurring for e in ev)


def test_newtimes():
    ev = newtimes.parse(read("newtimes_page9.html"), today=TODAY)
    check_common(ev, "newtimes")
    fault = [e for e in ev if e.title == "Faultline Band Live"][0]
    assert fault.date == "2026-10-11" and fault.town == "Nipomo" and fault.category == "music"
    assert fault.price == "Free" and "1-4 p.m." in fault.time
    karaoke = [e for e in ev if e.title == "Morro Bay Main Street Farmers Market"][0]
    assert karaoke.recurring and karaoke.category == "festival_market" and karaoke.date == "2026-10-10"


def test_newtimes_schedule_parser():
    s = newtimes._schedule
    assert s("Ongoing", TODAY) is None
    assert s("Second Thursday of every month, 6:30-8:30 p.m.", TODAY) is None
    assert s("Thu., Oct. 8, 6-8 p.m.", TODAY)[:3] == (date(2026, 10, 8), None, False)
    start, end, rec, _ = s("Through Oct. 29, 11 a.m.-5 p.m.", TODAY)
    assert (start, end, rec) == (TODAY, date(2026, 10, 29), False)
    assert s("Wednesdays, 6 p.m.", TODAY)[:3] == (date(2026, 10, 7), None, True)


def test_fetch_all_isolates_failures(monkeypatch):
    def boom():
        raise RuntimeError("down")

    monkeypatch.setitem(SOURCES, "goslo", boom)
    monkeypatch.setitem(SOURCES, "fremont", lambda: [Event(title="x", date="2026-10-06")])
    monkeypatch.setitem(SOURCES, "hellomorrobay", lambda: [])
    monkeypatch.setitem(SOURCES, "newtimes", lambda: [])
    r = fetch_all()
    assert isinstance(r["goslo"], RuntimeError)
    assert len(r["fremont"]) == 1 and r["hellomorrobay"] == []
