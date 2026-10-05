from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from slo_scraper import ig_fetch, store

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


class FakePost:
    def __init__(self, code, days_old, pinned=False, typename="GraphImage", caption="cap"):
        self.shortcode = code
        self.date_utc = (NOW - timedelta(days=days_old)).replace(tzinfo=None)  # instaloader: naive UTC
        self.is_pinned = pinned
        self.typename = typename
        self.caption = caption
        self.url = f"https://cdn/{code}.jpg"

    def get_sidecar_nodes(self):
        yield SimpleNamespace(display_url=f"https://cdn/{self.shortcode}_node0.jpg")
        yield SimpleNamespace(display_url=f"https://cdn/{self.shortcode}_node1.jpg")


class FakeProfile:
    posts: dict = {}

    def __init__(self, handle):
        self.handle = handle

    @classmethod
    def from_username(cls, context, handle):
        import instaloader
        if handle == "ratelimited":
            raise instaloader.exceptions.ConnectionException("429 Too Many Requests")
        if handle not in cls.posts:
            raise instaloader.exceptions.ProfileNotExistsException(handle)
        return cls(handle)

    def get_posts(self):
        return iter(self.posts[self.handle])


@pytest.fixture
def env(monkeypatch, tmp_path):
    import instaloader
    downloads = []

    def fake_dl(url, dest):
        downloads.append(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"img")
        return str(dest)

    monkeypatch.setattr(instaloader, "Profile", FakeProfile)
    monkeypatch.setattr(ig_fetch, "download_image", fake_dl)
    monkeypatch.setattr(ig_fetch.time, "sleep", lambda s: None)
    FakeProfile.posts = {}
    return SimpleNamespace(conn=store.connect(":memory:"), dir=tmp_path, downloads=downloads)


def run(env, handles, **kw):
    report = {}
    posts = ig_fetch.fetch_new_posts(SimpleNamespace(context=None), handles, env.conn, sleep=(0, 0),
                                     report=report, flyer_dir=env.dir, now=NOW, **kw)
    return posts, report


def test_stops_at_seen_and_skips_old_pinned(env):
    FakeProfile.posts["a"] = [
        FakePost("PIN_OLD", 90, pinned=True),
        FakePost("N1", 1), FakePost("N2", 2),
        FakePost("SEEN", 3), FakePost("N_AFTER_SEEN", 4),
    ]
    store.save_post(env.conn, ig_fetch.Post("SEEN", "a", "x", "", "u"))
    posts, rep = run(env, ["a"])
    assert [p.shortcode for p in posts] == ["N1", "N2"]
    assert store.post_seen(env.conn, "N1") and not store.post_seen(env.conn, "PIN_OLD")
    assert posts[0].url == "https://www.instagram.com/p/N1/" and posts[0].image_path.endswith("N1.jpg")
    assert posts[0].posted_at.startswith("2026-10-04") and rep["counts"] == {"a": 2}


def test_stops_at_old_and_caps(env):
    FakeProfile.posts["a"] = [FakePost(f"P{i}", i) for i in range(1, 6)] + [FakePost("OLD", 40), FakePost("P_OLDER", 41)]
    posts, _ = run(env, ["a"], max_per_account=3)
    assert [p.shortcode for p in posts] == ["P1", "P2", "P3"]
    posts, _ = run(env, ["a"], max_per_account=50)
    assert posts == []                                          # P1 already seen: stop immediately
    FakeProfile.posts["b"] = [FakePost("B1", 5), FakePost("OLD2", 31), FakePost("B_LATE", 32)]
    posts, _ = run(env, ["b"])
    assert [p.shortcode for p in posts] == ["B1"]


def test_recent_pinned_post_is_kept(env):
    FakeProfile.posts["a"] = [FakePost("PIN_NEW", 5, pinned=True), FakePost("N1", 1)]
    posts, _ = run(env, ["a"])
    assert {p.shortcode for p in posts} == {"PIN_NEW", "N1"}


def test_first_image_selection(env):
    FakeProfile.posts["a"] = [
        FakePost("SIDE", 1, typename="GraphSidecar"),
        FakePost("VID", 2, typename="GraphVideo"),
    ]
    run(env, ["a"])
    assert env.downloads == ["https://cdn/SIDE_node0.jpg", "https://cdn/VID.jpg"]


def test_missing_and_errors_do_not_stop_run(env):
    FakeProfile.posts["good"] = [FakePost("G1", 1)]
    posts, rep = run(env, ["nope", "ratelimited", "good"])
    assert [p.shortcode for p in posts] == ["G1"]
    assert rep["missing"] == ["nope"]
    assert "429" in rep["errors"]["ratelimited"]


def test_load_loader_missing_session(tmp_path):
    with pytest.raises(ig_fetch.SessionMissingError) as ei:
        ig_fetch.load_loader("burner", data_dir=tmp_path)
    msg = str(ei.value)
    assert "instaloader --login burner --sessionfile" in msg and "session-burner" in msg


def test_handles_from_config():
    h = ig_fetch.handles_from_config()
    assert "fremontslo" in h and len(h) == len(set(h))
