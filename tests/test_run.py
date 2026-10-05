import sys
from datetime import timedelta
import types
from datetime import date

import run as run_mod
from slo_scraper.models import Event
from slo_scraper.render import today_pacific

D3 = (today_pacific() + timedelta(days=3)).isoformat()
D4 = (today_pacific() + timedelta(days=4)).isoformat()


def _install(monkeypatch, name, **attrs):
    mod = types.ModuleType(f"slo_scraper.{name}")
    for k, v in attrs.items():
        setattr(mod, k, v)
    monkeypatch.setitem(sys.modules, f"slo_scraper.{name}", mod)
    import slo_scraper
    monkeypatch.setattr(slo_scraper, name, mod, raising=False)


def test_run_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(run_mod, "ROOT", tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "sources.yaml").write_text("instagram:\n  music:\n    - fremontslo\n", encoding="utf-8")
    (tmp_path / ".env").write_text("IG_USERNAME=tester\n", encoding="utf-8")

    soon = Event(title="Test Concert", date=D3, source_name="fremont", sources=["https://fremontslo.com/"])
    ig = Event(title="IG Show", date=D4, source_name="ig:fremontslo", confidence=0.5)
    seen = {}

    _install(monkeypatch, "listings", fetch_all=lambda: {"fremont": [soon], "goslo": RuntimeError("boom")})
    _install(monkeypatch, "ig_fetch",
             load_loader=lambda u: seen.setdefault("user", u) or object(),
             fetch_new_posts=lambda loader, handles, conn: seen.setdefault("handles", handles) and [])
    _install(monkeypatch, "extract", extract_pending=lambda conn: [ig])
    _install(monkeypatch, "dedupe", dedupe=lambda evs: evs,
             unique_counts=lambda by: {k: len(v) for k, v in by.items()})
    published = []
    import slo_scraper.publish as pub
    monkeypatch.setattr(pub, "publish", lambda d="site", dry_run=False: published.append(d) or True)

    out = tmp_path / "site"
    rc = run_mod.main(["--db", str(tmp_path / "e.db"), "--out", str(out)])
    assert rc == 0
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "Test Concert" in html and "IG Show" in html
    assert "boom" in html  # failed source visible in footer
    assert seen["user"] == "tester" and seen["handles"] == ["fremontslo"]
    assert published == [str(out)]
    log = (tmp_path / "data" / "run.log").read_text(encoding="utf-8")
    assert "yield report" in log and "goslo" in log and "boom" in log and "fremont" in log


def test_run_no_ig_no_publish_survives_missing_modules(tmp_path, monkeypatch):
    monkeypatch.setattr(run_mod, "ROOT", tmp_path)
    _install(monkeypatch, "listings", fetch_all=lambda: {})
    monkeypatch.setitem(sys.modules, "slo_scraper.dedupe", None)  # import fails -> graceful
    import slo_scraper.publish as pub
    monkeypatch.setattr(pub, "publish", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no publish")))
    rc = run_mod.main(["--no-ig", "--no-publish", "--db", str(tmp_path / "e.db"), "--out", str(tmp_path / "s")])
    assert rc == 0
    assert (tmp_path / "s" / "index.html").exists()
