from types import SimpleNamespace

import pytest

from slo_scraper import extract, store
from slo_scraper.models import Post


def tool_resp(inp):
    return SimpleNamespace(content=[SimpleNamespace(type="tool_use", name="record_events", input=inp)])


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.calls.append(kw)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def post(code="abc", at="2026-10-05T16:00:00+00:00", image=""):
    return Post(shortcode=code, account="fremontslo", posted_at=at, caption="cap",
                url=f"https://www.instagram.com/p/{code}/", image_path=image)


def ev(**kw):
    d = {"title": "Show", "date": "2026-10-10", "category": "music", "confidence": 0.9}
    d.update(kw)
    return d


def test_basic_fields():
    c = FakeClient([tool_resp({"is_event": True, "events": [ev(performers=["A"], venue="V")]})])
    ok, evs = extract.extract_post(post(), c)
    assert ok and len(evs) == 1
    e = evs[0]
    assert e.source_name == "ig:fremontslo" and e.sources == [post().url] and e.performers == ["A"]
    kw = c.calls[0]
    assert kw["model"] == "claude-haiku-4-5-20251001"
    assert kw["tool_choice"] == {"type": "tool", "name": "record_events"}
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_malformed_dates_dropped():
    evs_in = [ev(date="Friday"), ev(date="2026-13-45"), ev(date=""), ev(date="2026-10-12", title="Good")]
    ok, evs = extract.extract_post(post(), FakeClient([tool_resp({"is_event": True, "events": evs_in})]))
    assert [e.title for e in evs] == ["Good"]


def test_past_dated_dropped():
    evs_in = [ev(date="2026-10-04", title="Past"), ev(date="2026-10-05", title="Today")]
    ok, evs = extract.extract_post(post(), FakeClient([tool_resp({"is_event": True, "events": evs_in})]))
    assert [e.title for e in evs] == ["Today"]


def test_non_event():
    ok, evs = extract.extract_post(post(), FakeClient([tool_resp({"is_event": False, "events": []})]))
    assert (ok, evs) == (False, [])


def test_category_clamped():
    ok, evs = extract.extract_post(post(), FakeClient([tool_resp({"is_event": True, "events": [ev(category="rave")]})]))
    assert evs[0].category == "other"


def test_image_sent_resized(tmp_path):
    from PIL import Image
    p = tmp_path / "big.png"
    Image.new("RGB", (3000, 2000), "red").save(p)
    c = FakeClient([tool_resp({"is_event": False, "events": []})])
    extract.extract_post(post(image=str(p)), c)
    content = c.calls[0]["messages"][0]["content"]
    assert content[0]["type"] == "image" and content[0]["source"]["media_type"] == "image/jpeg"
    assert content[-1]["type"] == "text" and "2026-10-05" in content[-1]["text"]


def test_no_image_caption_only():
    c = FakeClient([tool_resp({"is_event": False, "events": []})])
    extract.extract_post(post(image="/nonexistent.jpg"), c)
    assert [b["type"] for b in c.calls[0]["messages"][0]["content"]] == ["text"]


def test_extract_pending_marks_and_no_resend():
    conn = store.connect(":memory:")
    store.save_post(conn, post("a"))
    store.save_post(conn, post("b"))
    c = FakeClient([
        tool_resp({"is_event": True, "events": [ev()]}),
        tool_resp({"is_event": False, "events": []}),
    ])
    out = extract.extract_pending(conn, c)
    assert len(out) == 1 and len(c.calls) == 2
    assert store.unextracted_posts(conn) == []
    assert extract.extract_pending(conn, c) == [] and len(c.calls) == 2
    assert len(store.upcoming_events(conn, "2026-10-05")) == 1


def test_failure_leaves_post_unextracted():
    conn = store.connect(":memory:")
    store.save_post(conn, post("a"))
    store.save_post(conn, post("b"))
    c = FakeClient([RuntimeError("boom"), tool_resp({"is_event": True, "events": [ev()]})])
    out = extract.extract_pending(conn, c)
    assert len(out) == 1
    assert [p.shortcode for p in store.unextracted_posts(conn)] == ["a"]


def test_prompt_asks_for_times_and_tool_has_time():
    assert "Doors 7 PM, show 8 PM" in extract.SYSTEM_PROMPT
    assert "time" in extract.TOOL_SCHEMA["input_schema"]["properties"]["events"]["items"]["properties"]


def test_time_passed_through():
    c = FakeClient([tool_resp({"is_event": True, "events": [ev(time="Doors 7 PM, show 8 PM")]})])
    assert extract.extract_post(post(), c)[1][0].time == "Doors 7 PM, show 8 PM"
