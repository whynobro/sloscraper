"""Instagram fetcher (instaloader). Burner account + saved session only.

Never logs in. Loads a session file created beforehand with e.g.
    instaloader --login <burner> --sessionfile data/session-<burner>
Run from the home PC only, never from CI.
"""
from __future__ import annotations

import argparse
import logging
import os
import random
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import yaml

from . import store
from .models import Post

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
FLYER_DIR = DATA_DIR / "flyers"
SOURCES_YAML = ROOT / "config" / "sources.yaml"


class SessionMissingError(RuntimeError):
    pass


def session_path(username: str, data_dir: Path = DATA_DIR) -> Path:
    return Path(data_dir) / f"session-{username}"


def load_loader(username: str, data_dir: Path = DATA_DIR):
    """Return an Instaloader with the saved session for `username` loaded."""
    import instaloader

    path = session_path(username, data_dir)
    if not path.exists():
        raise SessionMissingError(
            f"No Instagram session file at {path}.\n"
            f"Create one with the BURNER account (never your main):\n"
            f"  instaloader --login {username} --sessionfile {path}\n"
            f"or import Firefox cookies (log in to the burner in Firefox first):\n"
            f"  instaloader --load-cookies firefox --sessionfile {path}\n"
            f"then re-run."
        )
    loader = instaloader.Instaloader(
        download_pictures=False, download_videos=False, download_video_thumbnails=False,
        download_geotags=False, download_comments=False, save_metadata=False,
        compress_json=False, quiet=True, max_connection_attempts=1, request_timeout=30,
    )
    loader.load_session_from_file(username, str(path))
    return loader


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _image_url(post) -> str:
    """First image of the post: sidecar first node, else post.url (video thumbnail for videos)."""
    if getattr(post, "typename", "") == "GraphSidecar":
        try:
            first = next(iter(post.get_sidecar_nodes()))
            return first.display_url
        except Exception as exc:  # noqa: BLE001
            log.debug("sidecar lookup failed for %s: %r", post.shortcode, exc)
    return post.url


def download_image(url: str, dest: Path) -> str:
    """Download to dest; return str(dest) or '' on failure."""
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        dest.write_bytes(r.content)
        return str(dest)
    except Exception as exc:  # noqa: BLE001
        log.warning("image download failed for %s: %r", dest.name, exc)
        return ""


def fetch_new_posts(loader, handles: list[str], conn: sqlite3.Connection,
                    max_per_account: int = 12, max_age_days: int = 30,
                    sleep: tuple[float, float] = (20, 60),
                    report: dict | None = None,
                    flyer_dir: Path = FLYER_DIR,
                    now: datetime | None = None) -> list[Post]:
    """Fetch new posts for each handle, newest first.

    Stops an account at the first non-pinned post that is already in the DB or older
    than max_age_days. Pinned posts (shown first regardless of age) are skipped when
    old/seen without stopping. `report`, if given, is filled with
    {"missing": [handles], "errors": {handle: msg}, "counts": {handle: n_new}}.
    """
    import instaloader
    from instaloader.exceptions import ConnectionException, ProfileNotExistsException

    report = report if report is not None else {}
    report.setdefault("missing", [])
    report.setdefault("errors", {})
    report.setdefault("counts", {})
    cutoff = _utc(now or datetime.now(timezone.utc)) - timedelta(days=max_age_days)
    out: list[Post] = []

    for i, handle in enumerate(handles):
        if i > 0 and sleep and sleep[1] > 0:
            time.sleep(random.uniform(*sleep))
        n_new = 0
        try:
            profile = instaloader.Profile.from_username(loader.context, handle)
            for p in profile.get_posts():
                pinned = bool(getattr(p, "is_pinned", False))
                posted = _utc(p.date_utc)
                if posted < cutoff:
                    if pinned:
                        continue
                    break
                if store.post_seen(conn, p.shortcode):
                    if pinned:
                        continue
                    break
                if n_new >= max_per_account:
                    break
                img = download_image(_image_url(p), flyer_dir / f"{p.shortcode}.jpg")
                post = Post(
                    shortcode=p.shortcode, account=handle,
                    posted_at=posted.isoformat(timespec="seconds"),
                    caption=p.caption or "",
                    url=f"https://www.instagram.com/p/{p.shortcode}/",
                    image_path=img,
                )
                store.save_post(conn, post)
                out.append(post)
                n_new += 1
        except ProfileNotExistsException:
            log.warning("handle not found: %s", handle)
            report["missing"].append(handle)
        except ConnectionException as exc:   # includes 401/403/429 (TooManyRequests)
            log.warning("connection error for %s: %s", handle, exc)
            report["errors"][handle] = str(exc)
        except Exception as exc:  # noqa: BLE001 - never let one account kill the run
            log.warning("unexpected error for %s: %r", handle, exc)
            report["errors"][handle] = repr(exc)
        report["counts"][handle] = n_new
    return out


def handles_from_config(path: Path = SOURCES_YAML) -> list[str]:
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    seen, out = set(), []
    for group in (cfg.get("instagram") or {}).values():
        for h in group or []:
            h = str(h).strip().lstrip("@")
            if h and h not in seen:
                seen.add(h)
                out.append(h)
    return out


def main(argv: list[str] | None = None) -> int:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    ap = argparse.ArgumentParser(description="Fetch new Instagram posts for handles.")
    ap.add_argument("--handles", help="comma-separated handles (default: all in config/sources.yaml)")
    ap.add_argument("--limit", type=int, default=12, help="max new posts per account")
    ap.add_argument("--max-age-days", type=int, default=30)
    ap.add_argument("--dry-run", action="store_true", help="use an in-memory DB (nothing marked seen)")
    ap.add_argument("--username", default=os.environ.get("IG_USERNAME", ""))
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if not args.username:
        ap.error("IG_USERNAME not set (put it in .env) or pass --username")
    handles = ([h.strip().lstrip("@") for h in args.handles.split(",") if h.strip()]
               if args.handles else handles_from_config())
    try:
        loader = load_loader(args.username)
    except SessionMissingError as exc:
        print(exc)
        return 2
    conn = store.connect(":memory:" if args.dry_run else store.DEFAULT_DB)
    report: dict = {}
    posts = fetch_new_posts(loader, handles, conn, max_per_account=args.limit,
                            max_age_days=args.max_age_days, report=report)
    for p in posts:
        print(f"[{p.account}] {p.posted_at} {p.url}\n  img={p.image_path or '-'}\n  {p.caption[:160]!r}")
    print(f"\n{len(posts)} new posts; missing handles: {report['missing'] or 'none'}; "
          f"errors: {report['errors'] or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
