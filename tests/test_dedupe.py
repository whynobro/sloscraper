from slo_scraper.dedupe import dedupe, unique_counts
from slo_scraper.models import Event


def L(title, date="2026-10-05", town="San Luis Obispo", **kw):
    return Event(title=title, date=date, town=town, source_name=kw.pop("source_name", "fremont"),
                 sources=kw.pop("sources", ["https://fremontslo.com/e"]), **kw)


def IG(title, date="2026-10-05", town="San Luis Obispo", **kw):
    return Event(title=title, date=date, town=town, source_name="ig:fremontslo", confidence=0.8,
                 sources=["https://instagram.com/p/x/"], flyer_path="flyer.jpg", **kw)


def test_ig_and_listing_merge():
    a = L("Lukas Nelson & Molly Tuttle", price="$50", venue="Fremont Theater", ticket_url="http://t")
    b = IG("Lukas Nelson & Molly Tuttle LIVE at the Fremont", time="8pm")
    out = dedupe([a, b])
    assert len(out) == 1
    m = out[0]
    assert m.title == "Lukas Nelson & Molly Tuttle" and m.confidence == 1.0
    assert m.time == "8pm" and m.price == "$50"
    assert set(m.sources) == {"https://fremontslo.com/e", "https://instagram.com/p/x/"}
    assert m.source_name == "fremont,ig:fremontslo"
    assert m.flyer_path == "flyer.jpg"


def test_different_dates_dont_merge():
    assert len(dedupe([L("Morgan Page"), L("Morgan Page", date="2026-10-07")])) == 2


def test_different_towns_dont_merge():
    assert len(dedupe([L("Open Mic Night"), L("Open Mic Night", town="Morro Bay")])) == 2


def test_empty_town_matches_anything():
    assert len(dedupe([L("Morgan Page"), L("Morgan Page", town="")])) == 1


def test_same_venue_date_different_acts_separate():
    a = L("Trivia Night", venue="Fremont")
    b = L("Michelle Branch", venue="Fremont")
    assert len(dedupe([a, b])) == 2


def test_performer_match():
    a = L("An Evening of Bluegrass", performers=["Molly Tuttle"])
    b = IG("Friday show", performers=["Molly Tuttle"])
    assert len(dedupe([a, b])) == 1


def test_no_inputs_mutated():
    a, b = L("Morgan Page"), IG("Morgan Page", venue="Fremont")
    dedupe([a, b])
    assert a.venue == "" and a.sources == ["https://fremontslo.com/e"]


def test_unique_counts():
    by = {
        "fremont": [L("Morgan Page"), L("Michelle Branch", date="2026-10-06")],
        "ig:fremontslo": [IG("Morgan Page LIVE at the Fremont"), IG("Poetry Slam", date="2026-10-09")],
        "goslo": [L("Morgan Page", source_name="goslo")],
    }
    assert unique_counts(by) == {"fremont": 1, "ig:fremontslo": 1, "goslo": 0}
