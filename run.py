"""SLO Events pipeline: listings + Instagram -> SQLite -> dedupe -> site/index.html -> gh-pages.

Usage: python run.py [--no-ig] [--no-publish] [--db PATH] [--out site]
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

log = logging.getLogger("slo")


def setup_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        if getattr(h, "_slo", False):
            root.removeHandler(h)
            h.close()
    for h in (logging.StreamHandler(sys.stdout), logging.FileHandler(log_path, encoding="utf-8")):
        h.setFormatter(fmt)
        h._slo = True
        root.addHandler(h)


def load_ig_handles(config_path: Path) -> list[str]:
    import yaml
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    ig = cfg.get("instagram") or []
    if isinstance(ig, dict):
        ig = [h for group in ig.values() for h in (group or [])]
    seen, out = set(), []
    for h in ig:
        h = str(h).strip().lstrip("@")
        if h and h not in seen:
            seen.add(h)
            out.append(h)
    return out


def run_instagram(conn, root: Path) -> list:
    """Fetch IG posts and extract events. Never raises; returns newly extracted events."""
    try:
        from dotenv import load_dotenv
        load_dotenv(root / ".env")
        username = os.environ.get("IG_USERNAME", "")
        handles = load_ig_handles(root / "config" / "sources.yaml")
        from slo_scraper import ig_fetch
        loader = ig_fetch.load_loader(username)
        posts = ig_fetch.fetch_new_posts(loader, handles, conn)
        log.info("instagram: %d new posts from %d handles", len(posts), len(handles))
    except Exception as e:
        log.error("instagram fetch failed: %s: %s", type(e).__name__, e)
    try:
        from slo_scraper import extract
        events = extract.extract_pending(conn)
        log.info("extract: %d events from pending posts", len(events))
        return events
    except Exception as e:
        log.error("extract failed: %s: %s", type(e).__name__, e)
        return []


def format_yield_table(stats: dict) -> str:
    rows = [("source", "events", "unique", "error")]
    for name in sorted(stats):
        s = stats[name]
        rows.append((name, str(s.get("events", 0)), str(s.get("unique", "")), str(s.get("error") or "")))
    widths = [max(len(r[i]) for r in rows) for i in range(3)]
    lines = []
    for r in rows:
        lines.append("  ".join(r[i].ljust(widths[i]) for i in range(3)) + "  " + r[3])
    return "\n".join(l.rstrip() for l in lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="SLO Events pipeline")
    ap.add_argument("--no-ig", action="store_true", help="skip Instagram fetch + extraction")
    ap.add_argument("--no-publish", action="store_true", help="render only, do not push gh-pages")
    ap.add_argument("--db", default=None, help="SQLite path (default data/events.db)")
    ap.add_argument("--out", default="site", help="output directory for the site")
    args = ap.parse_args(argv)

    setup_logging(ROOT / "data" / "run.log")
    log.info("run start")

    from slo_scraper import store
    from slo_scraper.render import render, today_pacific

    conn = store.connect(args.db) if args.db else store.connect()
    errors: dict[str, str] = {}

    # 1. listings
    try:
        from slo_scraper import listings
        results = listings.fetch_all()
    except Exception as e:
        log.error("listings.fetch_all failed: %s: %s", type(e).__name__, e)
        results = {}
    for name, res in results.items():
        if isinstance(res, Exception):
            errors[name] = f"{type(res).__name__}: {res}"
            log.error("source %s failed: %s", name, errors[name])
            continue
        try:
            store.save_events(conn, res)
            log.info("source %s: %d events", name, len(res))
        except Exception as e:
            errors[name] = f"save failed: {e}"
            log.error("source %s save failed: %s", name, e)

    # 2. Instagram
    if not args.no_ig:
        ig_events = run_instagram(conn, ROOT)
        if ig_events:
            try:
                store.save_events(conn, ig_events)
            except Exception as e:
                log.error("saving IG events failed: %s", e)

    # 3. upcoming -> dedupe -> render
    today = today_pacific()
    upcoming = store.upcoming_events(conn, today.isoformat())
    by_source: dict[str, list] = {}
    for ev in upcoming:
        by_source.setdefault(ev.source_name or "unknown", []).append(ev)

    unique: dict[str, int] = {}
    try:
        from slo_scraper import dedupe
        unique = dedupe.unique_counts(by_source)
        deduped = dedupe.dedupe(upcoming)
    except Exception as e:
        log.error("dedupe failed, rendering undeduped: %s: %s", type(e).__name__, e)
        deduped = upcoming

    stats: dict[str, dict] = {}
    for name in set(by_source) | set(results) | set(errors):
        stats[name] = {"events": len(by_source.get(name, [])), "unique": unique.get(name, ""),
                       "error": errors.get(name, "")}
    for name, s in stats.items():
        try:
            store.record_source_run(conn, name, s["events"], unique.get(name), s["error"] or None)
        except Exception as e:
            log.error("record_source_run %s failed: %s", name, e)

    log.info("yield report:\n%s", format_yield_table(stats))
    page = render(deduped, out_dir=args.out, generated_at=datetime.now(timezone.utc),
                  source_stats=stats, today=today)
    log.info("rendered %d events to %s", len(deduped), page)

    # 4. publish
    if not args.no_publish:
        from slo_scraper.publish import publish
        ok = publish(args.out)
        log.info("publish %s", "ok" if ok else "FAILED")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
