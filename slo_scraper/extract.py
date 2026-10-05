"""Claude-vision extraction: Instagram post (flyer + caption) -> Events."""
from __future__ import annotations

import base64
import io
import logging
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from . import store
from .models import CATEGORIES, Event, Post

log = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5-20251001"
MAX_SIDE = 1568
MAX_TOKENS = 4096
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

SYSTEM_PROMPT = (
    "You read promotional posts (flyer image plus caption) from venues and organizers in "
    "San Luis Obispo County, California, and record the upcoming events they announce by "
    "calling the record_events tool exactly once.\n"
    "\n"
    "Rules:\n"
    "- Resolve relative dates (\"this Friday\", \"tonight\", \"tomorrow\", \"10/12\", \"Oct 12\") "
    "using the POST date given in the message, not the real current date. If a date has no "
    "year, use the post date's year; if that month/day has already passed relative to the "
    "post date, use the next year.\n"
    "- Set is_event=false and events=[] for menus, hiring posts, merch, recaps or photos of "
    "past events, thank-you posts, and generic promotions with no specific upcoming event.\n"
    "- One post can announce several events (for example a monthly lineup flyer). Return "
    "every event as its own item.\n"
    "- Never invent dates. If an event's date cannot be read or determined, skip that event.\n"
    "- Dates are YYYY-MM-DD in local Pacific time. Use end_date only for multi-day events.\n"
    "- If the venue or town is not stated, infer it from the posting account when the account "
    "is itself a venue; otherwise leave it empty. Use canonical town names such as San Luis "
    "Obispo, Morro Bay, Paso Robles, Pismo Beach, Arroyo Grande, Avila Beach, Los Osos, "
    "Cayucos, Cambria, Atascadero.\n"
    "- title is the event name as advertised; performers lists the artists or hosts.\n"
    "- confidence is 0 to 1: how sure you are that the details are correct and upcoming.\n"
    "- Leave unknown string fields as empty strings."
)

TOOL_NAME = "record_events"
TOOL_SCHEMA = {
    "name": TOOL_NAME,
    "description": "Record the upcoming events announced in this post.",
    "input_schema": {
        "type": "object",
        "properties": {
            "is_event": {"type": "boolean",
                         "description": "True if the post announces at least one upcoming event."},
            "events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "performers": {"type": "array", "items": {"type": "string"}},
                        "category": {"type": "string", "enum": list(CATEGORIES)},
                        "venue": {"type": "string"},
                        "town": {"type": "string"},
                        "date": {"type": "string", "description": "YYYY-MM-DD"},
                        "end_date": {"type": "string", "description": "YYYY-MM-DD, multi-day only"},
                        "time": {"type": "string"},
                        "price": {"type": "string"},
                        "ticket_url": {"type": "string"},
                        "age_limit": {"type": "string"},
                        "recurring": {"type": "boolean"},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                    "required": ["title", "date", "category", "confidence"],
                },
            },
        },
        "required": ["is_event", "events"],
    },
}

_client = None


def _get_client():
    global _client
    if _client is None:
        from dotenv import load_dotenv
        import anthropic
        env = Path.cwd() / ".env"
        if env.exists():
            load_dotenv(env)
        _client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
    return _client


def _post_date(post: Post) -> date:
    try:
        dt = datetime.fromisoformat(post.posted_at.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc).date()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        return dt.astimezone(ZoneInfo("America/Los_Angeles")).date()
    except Exception:
        return (dt - timedelta(hours=7)).date()


def _encode_image(path: str) -> Optional[dict]:
    if not path or not Path(path).is_file():
        return None
    try:
        from PIL import Image
        with Image.open(path) as im:
            im = im.convert("RGB")
            im.thumbnail((MAX_SIDE, MAX_SIDE))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=85)
    except Exception as e:  # unreadable image: fall back to caption only
        log.warning("image unreadable %s: %s", path, e)
        return None
    data = base64.standard_b64encode(buf.getvalue()).decode()
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}


def _valid_date(s) -> Optional[str]:
    if not isinstance(s, str) or not _DATE_RE.match(s.strip()):
        return None
    try:
        datetime.strptime(s.strip(), "%Y-%m-%d")
    except ValueError:
        return None
    return s.strip()


def _s(v) -> str:
    return v.strip() if isinstance(v, str) else ""


def _build_events(raw, post: Post, cutoff: date) -> list[Event]:
    out: list[Event] = []
    for r in raw if isinstance(raw, list) else []:
        if not isinstance(r, dict):
            continue
        d = _valid_date(r.get("date"))
        title = _s(r.get("title"))
        if not d or not title:
            continue
        if d < cutoff.isoformat():
            continue
        end = _valid_date(r.get("end_date"))
        if end and end < d:
            end = None
        cat = r.get("category")
        if cat not in CATEGORIES:
            cat = "other"
        perf = r.get("performers")
        perf = [p.strip() for p in perf if isinstance(p, str) and p.strip()] if isinstance(perf, list) else []
        try:
            conf = max(0.0, min(1.0, float(r.get("confidence", 0.5))))
        except (TypeError, ValueError):
            conf = 0.5
        out.append(Event(
            title=title, date=d, category=cat, performers=perf,
            venue=_s(r.get("venue")), town=_s(r.get("town")), end_date=end,
            time=_s(r.get("time")), price=_s(r.get("price")),
            ticket_url=_s(r.get("ticket_url")), age_limit=_s(r.get("age_limit")),
            recurring=bool(r.get("recurring", False)), confidence=conf,
            sources=[post.url] if post.url else [], source_name=f"ig:{post.account}",
            flyer_path=post.image_path,
        ))
    return out


def extract_post(post: Post, client=None, today=None) -> tuple[bool, list[Event]]:
    """Send one post to Claude. Returns (is_event, events). Raises on API failure.

    today (date or YYYY-MM-DD) optionally raises the past-date cutoff above the post date.
    """
    client = client or _get_client()
    pdate = _post_date(post)
    cutoff = pdate
    if today is not None:
        t = date.fromisoformat(today) if isinstance(today, str) else today
        cutoff = max(pdate, t)
    text = (
        f"Account: @{post.account}\n"
        f"Post date: {pdate.isoformat()} ({pdate.strftime('%A')})\n"
        f"Caption:\n{post.caption or '(none)'}"
    )
    content: list[dict] = []
    img = _encode_image(post.image_path)
    if img:
        content.append(img)
    content.append({"type": "text", "text": text})
    resp = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        tools=[TOOL_SCHEMA],
        tool_choice={"type": "tool", "name": TOOL_NAME},
        messages=[{"role": "user", "content": content}],
    )
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", TOOL_NAME) == TOOL_NAME:
            inp = block.input or {}
            if not inp.get("is_event"):
                return False, []
            evs = _build_events(inp.get("events"), post, cutoff)
            return bool(evs), evs
    raise RuntimeError("model returned no tool_use block")


def extract_pending(conn: sqlite3.Connection, client=None, limit: Optional[int] = None) -> list[Event]:
    """Extract every unextracted post. Never raises; failed posts stay pending."""
    out: list[Event] = []
    try:
        posts = store.unextracted_posts(conn)
        if limit is not None:
            posts = posts[:limit]
        if posts and client is None:
            client = _get_client()
    except Exception as e:
        log.error("extract_pending setup failed: %s", e)
        return out
    for post in posts:
        try:
            is_event, evs = extract_post(post, client)
            if evs:
                store.save_events(conn, evs)
            store.mark_extracted(conn, post.shortcode, is_event)
            out.extend(evs)
        except Exception as e:
            log.error("extract failed for %s: %s", post.shortcode, e)
    return out
