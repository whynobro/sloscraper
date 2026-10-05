"""Run extract_post over flyer fixtures and report accuracy.

Usage: python scripts/eval_extract.py [folder] [--env PATH_TO_.env]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from slo_scraper.models import Post  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", nargs="?", default=str(ROOT / "tests" / "fixtures" / "flyers"))
    ap.add_argument("--env", help="extra .env file to load for ANTHROPIC_API_KEY")
    args = ap.parse_args()

    load_dotenv(Path.cwd() / ".env")
    load_dotenv(ROOT / ".env")
    if args.env:
        load_dotenv(args.env)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set (put it in .env or the environment, or pass --env).")
        return 2

    from slo_scraper.extract import extract_post

    folder = Path(args.folder)
    expected = json.loads((folder / "expected.json").read_text(encoding="utf8"))
    tot_exp = tot_hit = tot_extra = files_ok = 0
    for name, meta in expected.items():
        post = Post(shortcode=Path(name).stem, account=meta["account"], posted_at=meta["posted_at"],
                    caption=meta.get("caption", ""), url=f"https://www.instagram.com/p/{Path(name).stem}/",
                    image_path=str(folder / name))
        try:
            is_event, evs = extract_post(post)
        except Exception as e:
            print(f"== {name}: ERROR {type(e).__name__}: {e}")
            tot_exp += len(meta["expected"])
            continue
        exp = {(x["date"]) for x in meta["expected"]}
        got = {e.date for e in evs}
        hit = len(exp & got)
        extra = len(got - exp)
        tot_exp += len(exp); tot_hit += hit; tot_extra += extra
        ok = hit == len(exp) and extra == 0 and (bool(exp) == is_event)
        files_ok += ok
        print(f"== {name}: {'OK' if ok else 'MISS'} is_event={is_event}")
        print("   expected:", [(x["title"], x["date"]) for x in meta["expected"]])
        for e in evs:
            print(f"   got: {e.title!r} {e.date} venue={e.venue!r} town={e.town!r} time={e.time!r} "
                  f"cat={e.category} conf={e.confidence}")
        if meta.get("expected_time") and not any(e.time for e in evs):
            print("   WARN: expected a time, got none:", meta["expected_time"])
    print(f"\nfiles ok: {files_ok}/{len(expected)}  event-date recall: {tot_hit}/{tot_exp}  extra events: {tot_extra}")
    return 0 if files_ok == len(expected) else 1


if __name__ == "__main__":
    sys.exit(main())
