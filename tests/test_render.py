import json
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from slo_scraper.models import Event
from slo_scraper.render import calendar_url, render, section_for

FIXTURE = Path(__file__).parent / "fixtures" / "sample_events.json"
TODAY = date(2026, 10, 5)  # Monday


def load():
    return [Event.from_dict(d) for d in json.loads(FIXTURE.read_text(encoding="utf-8"))]


def html_of(tmp_path, **kw):
    kw.setdefault("today", TODAY)
    p = render(load(), out_dir=tmp_path / "site", generated_at=datetime(2026, 10, 5, 17, tzinfo=timezone.utc), **kw)
    return p.read_text(encoding="utf-8")


def test_upcoming_present_past_hidden(tmp_path):
    html = html_of(tmp_path)
    assert "Khruangbin" in html
    assert "Art After Dark" in html
    assert "Morro Bay Harbor Festival" in html
    assert "Old Town Jazz Night" not in html


def test_sections(tmp_path):
    evs = {e.title: e for e in load()}
    assert section_for(evs["Khruangbin"], TODAY) == "today"
    assert section_for(evs["Tomorrow Open Mic"], TODAY) == "tomorrow"
    assert section_for(evs["Comedy Night with Maria Bamford"], TODAY) == "week"
    assert section_for(evs["Plein Air Landscapes Exhibit"], TODAY) == "ongoing"
    assert section_for(evs["Friday Night Rock: Desert Highway"], TODAY) == "weekend"
    assert section_for(evs["Sunset Beach Concert"], TODAY) == "weekend"
    assert section_for(evs["Morro Bay Harbor Festival"], TODAY) == "weekend"
    assert section_for(evs["Wine & Cheese Pairing Dinner"], TODAY) == "later"
    assert section_for(evs["Thursday Trivia Night"], TODAY) == "recurring"
    # on a Saturday the weekend starts today
    assert section_for(evs["Sunset Beach Concert"], date(2026, 10, 10)) == "today"
    assert section_for(evs["Kayak the Estuary Guided Tour"], date(2026, 10, 10)) == "tomorrow"
    # multi-day event already underway counts as today
    assert section_for(evs["Morro Bay Harbor Festival"], date(2026, 10, 11)) == "today"
    html = html_of(tmp_path)
    assert html.index(">Today") < html.index(">Tomorrow") < html.index("This weekend") < html.index("Rest of this week")         < html.index(">Later") < html.index("Ongoing exhibits") < html.index(">Recurring")
    assert "Far Future Gala" not in html  # beyond 60 days
    assert "Fri, Oct 9" in html and "Mon, Oct 5" in html
    assert "Oct 10 to Oct 12" in html
    assert "<details>" in html


def test_calendar_url_timed_and_allday():
    ev = Event(title="Khruangbin & Friends", date="2026-10-05", time="8:00 PM", venue="Fremont Theater",
               town="San Luis Obispo")
    url = calendar_url(ev)
    assert url.startswith("https://calendar.google.com/calendar/render?action=TEMPLATE")
    q = parse_qs(urlparse(url).query)
    assert q["text"] == ["Khruangbin & Friends"]
    assert q["dates"] == ["20261005T200000/20261005T220000"]
    assert q["ctz"] == ["America/Los_Angeles"]
    assert q["location"] == ["Fremont Theater, San Luis Obispo"]

    ev2 = Event(title="Fest", date="2026-10-10", end_date="2026-10-12", time="Doors 7, show 8")
    q2 = parse_qs(urlparse(calendar_url(ev2)).query)
    assert q2["dates"] == ["20261010/20261013"]
    assert "ctz" not in q2

    assert parse_qs(urlparse(calendar_url(Event(title="x", date="2026-10-05", time="7pm"))).query)["dates"] == [
        "20261005T190000/20261005T210000"]


def test_script_title_escaped(tmp_path):
    html = html_of(tmp_path)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_badges_and_labels(tmp_path):
    html = html_of(tmp_path)
    assert html.count(">check flyer<") == 1
    assert ">Instagram<" in html
    assert ">fremontslo.com<" in html
    assert "Festivals &amp; Markets" in html


def test_source_stats_footer_and_flyer(tmp_path):
    from PIL import Image
    img = tmp_path / "f.png"
    Image.new("RGB", (1000, 1500), "red").save(img)
    evs = [Event(title="With Flyer", date="2026-10-06", flyer_path=str(img))]
    p = render(evs, out_dir=tmp_path / "site", today=TODAY,
               source_stats={"fremont": {"events": 5, "unique": 3, "error": None},
                             "goslo": {"events": 0, "unique": 0, "error": "Timeout"}})
    html = p.read_text(encoding="utf-8")
    assert "Timeout" in html and "fremont" in html
    thumbs = list((tmp_path / "site" / "flyers").glob("*.jpg"))
    assert len(thumbs) == 1
    with Image.open(thumbs[0]) as t:
        assert t.width == 400
    assert 'loading="lazy"' in html


def test_later_weeks_collapsed_and_compact(tmp_path):
    html = html_of(tmp_path)
    assert 'class="wk"' in html and "Week of Nov 2" in html  # Art After Dark (Nov 6) is >14 days out
    assert "Plein Air Landscapes Exhibit" in html
    assert 'class="card cat-music"' in html
