"""Shared helpers for listing scrapers."""
from __future__ import annotations

import html
import re
from datetime import date

import requests

from ..models import CATEGORIES, TOWNS

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
TIMEOUT = 20


def http_get(url: str, **kw) -> requests.Response:
    kw.setdefault("timeout", TIMEOUT)
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}
    headers.update(kw.pop("headers", {}))
    r = requests.get(url, headers=headers, **kw)
    r.raise_for_status()
    return r


def fetch_text(url: str, **kw) -> str:
    r = http_get(url, **kw)
    # requests guesses latin-1 for some servers with no charset; prefer utf-8
    if not r.encoding or r.encoding.lower() in ("iso-8859-1", "latin-1"):
        r.encoding = "utf-8"
    return r.text


def today() -> date:
    return date.today()


_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0000FE0F\U0000200D\U00002B00-\U00002BFF]+"
)


def clean(s: str) -> str:
    """Unescape entities, drop emoji, collapse whitespace."""
    s = html.unescape(s or "")
    s = _EMOJI.sub("", s)
    return re.sub(r"\s+", " ", s).strip()


_TOWN_ALIASES = {
    "slo": "San Luis Obispo",
    "san luis obispo": "San Luis Obispo",
    "south coast slo county": "",
    "pismo": "Pismo Beach",
    "avila": "Avila Beach",
    "paso": "Paso Robles",
    "morro bay": "Morro Bay",
}


def normalize_town(s: str) -> str:
    key = clean(s).lower().rstrip(".")
    if key in _TOWN_ALIASES:
        return _TOWN_ALIASES[key]
    for t in TOWNS:
        if t.lower() == key:
            return t
    return clean(s)


# Anything clearly outside SLO County (drop). Matched against venue/town/title text.
OUT_OF_COUNTY = (
    "carson city", "reno", "las vegas", "santa maria", "santa barbara", "lompoc",
    "bakersfield", "salinas", "fresno", "los angeles", "san francisco",
    "buellton", "solvang", "orcutt", "los alamos", "goleta", "carpinteria", "ventura", "king city",
    "santa ynez", "guadalupe", "taft", "maricopa",
)


def out_of_county(*texts: str) -> bool:
    blob = " ".join(texts).lower()
    return any(re.search(r"\b" + re.escape(k) + r"\b", blob) for k in OUT_OF_COUNTY)


_CAT_RULES = (
    ("comedy", r"comedy|comedian|stand-?up|open mic comedy|kill tony|improv"),
    ("film_theater", r"\bfilm\b|movie|screening|cinema|theat(er|re)\b|play\b|musical|rocky horror|opera|ballet"),
    ("music", r"live music|concert|\btour\b|\bband\b|jazz|orchestra|symphony|karaoke|open mic|album|\bdj\b|"
              r"acoustic|festival of music|bluegrass|\brock\b|blues|reggae|choir|recital|\bmusic\b"),
    ("art", r"art walk|art after dark|gallery|exhibit|exhibition|artist|painting|pottery|sculpt|"
            r"photograph|\bart\b|craft fair|mural"),
    ("festival_market", r"farmers.? market|festival|fair\b|market|expo\b|swap meet|parade|\bsale\b|fundraiser"),
    ("food_drink", r"wine|beer|brewery|tasting|dinner|brunch|food|trivia|bingo|happy hour|cocktail|oyster|chowder"),
    ("outdoor", r"hike|\bwalk\b|\brun\b|\b5k\b|\b10k\b|\bsurf|kayak|paddle|\bbike|cycling|nature|wildlife|beach|garden|"
               r"tour of|trail|yoga|whale"),
    ("community", r"community|volunteer|meeting|support group|workshop|class\b|kids|family|library|talk\b|lecture"),
)


def guess_category(text: str, default: str = "other") -> str:
    t = clean(text).lower()
    for cat, pat in _CAT_RULES:
        if re.search(pat, t):
            return cat
    return default


_RECURRING = re.compile(
    r"trivia|karaoke|farmers.? market|open mic|bingo|weekly|every (mon|tues|wednes|thurs|fri|satur|sun)day|"
    r"\b(mon|tues|wednes|thurs|fri|satur|sun)days?\b|jazz night|taco tuesday|happy hour|lunch sets|afternoon sets",
    re.I,
)


def looks_recurring(text: str) -> bool:
    return bool(_RECURRING.search(text or ""))


def assert_category(c: str) -> str:
    return c if c in CATEGORIES else "other"


# Non-fun listings (support groups, fitness classes, club meetings...). Applied by name.
_EXCLUDE = re.compile(
    r"support group|anonymous|toastmasters|\byoga\b|tai chi|qi gong|\bpilates\b|fitness|"
    r"exercise class|body fusion|zumba|\bmeetings?\b|class for adults|\blessons?\b|"
    r"\bgroups? (meeting|session)|\brecovery\b|\bhealing\b|\bmeditat|coffee meeting|"
    r"\btops\b|take off pounds|\bcare crew\b|\bshowers? with\b|\bnotary\b|\bcpr\b",
    re.I,
)
_EXCLUDE_IF_RECURRING = re.compile(r"\bworkshops?\b|\bclasses\b|\bclass\b|\bcourse\b|\bclub\b", re.I)
_KEEP = re.compile(r"trivia|bingo|karaoke|open mic|live music|farmers.? market|concert|comedy", re.I)


def is_excluded(title: str, recurring: bool = False) -> bool:
    """True for listings that are not fun events (meetings, support groups, fitness classes)."""
    t = clean(title)
    if _KEEP.search(t):
        return False
    if _EXCLUDE.search(t):
        return True
    return recurring and bool(_EXCLUDE_IF_RECURRING.search(t))
