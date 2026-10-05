"""Merge the same event seen in several sources. Pure functions, no I/O."""
from __future__ import annotations

import re
from dataclasses import replace

from rapidfuzz import fuzz

from .models import Event

THRESHOLD = 85
_NOISE = {"live", "presents", "present", "presented", "tickets", "ticket", "w", "with", "by", "the", "and", "feat", "featuring"}
_SUPPORT = re.compile(r"\s+(?:with|w/|feat\.?|featuring|ft\.?)\s+")
_TRAILING_AT = re.compile(r"\s+(?:at|@)\s+.*$")


def norm_title(s: str) -> str:
    s = (s or "").lower()
    s = _TRAILING_AT.sub("", s)
    if " presents " in s:  # "The Bunker SLO presents Karaoke" -> "Karaoke"
        s = s.split(" presents ", 1)[1] or s
    # "Juice with special guest X" -> headliner "Juice"
    head = _SUPPORT.split(s, maxsplit=1)[0]
    if head.strip():
        s = head
    s = re.sub(r"[^\w\s]", " ", s)
    words = [w for w in s.split() if w not in _NOISE]
    return " ".join(words)


def norm_town(s: str) -> str:
    return re.sub(r"[^a-z ]", "", (s or "").lower()).strip()


def _perf_key(e: Event) -> str:
    return " ".join(sorted(norm_title(p) for p in e.performers if p and p.strip())).strip()


def _towns_compatible(a: Event, b: Event) -> bool:
    ta, tb = norm_town(a.town), norm_town(b.town)
    return not ta or not tb or ta == tb


def _fuzzy(a: str, b: str) -> bool:
    """Fuzzy match, but single-token strings must match exactly ("Morgan" != "Morgan Page")."""
    if not a or not b:
        return False
    if len(a.split()) == 1 or len(b.split()) == 1:
        return a == b
    return fuzz.token_set_ratio(a, b) >= THRESHOLD


def _names_match(a: Event, b: Event) -> bool:
    if _fuzzy(norm_title(a.title), norm_title(b.title)):
        return True
    return _fuzzy(_perf_key(a), _perf_key(b))


def _span(e: Event) -> tuple[str, str]:
    return e.date, max(e.end_date or e.date, e.date)


def _same(a: Event, b: Event) -> bool:
    if not _towns_compatible(a, b):
        return False
    if a.date == b.date:
        return _names_match(a, b)
    # Same multi-day run listed with different start dates: both multi-day, ranges overlap,
    # titles (not performers) match.
    if a.end_date and b.end_date:
        (s1, e1), (s2, e2) = _span(a), _span(b)
        if s1 <= e2 and s2 <= e1:
            return _fuzzy(norm_title(a.title), norm_title(b.title))
    return False


def _names(e: Event) -> list[str]:
    return [n.strip() for n in (e.source_name or "").split(",") if n.strip()]


def _merge(group: list[Event]) -> Event:
    order = sorted(range(len(group)), key=lambda i: (-group[i].confidence, i))
    ranked = [group[i] for i in order]
    merged = replace(ranked[0], performers=list(ranked[0].performers), sources=list(ranked[0].sources))

    for other in ranked[1:]:
        for f in ("venue", "town", "time", "price", "ticket_url", "age_limit", "description"):
            if not getattr(merged, f) and getattr(other, f):
                setattr(merged, f, getattr(other, f))
        if not merged.end_date and other.end_date:
            merged.end_date = other.end_date
        if not merged.performers and other.performers:
            merged.performers = list(other.performers)
        if merged.category == "other" and other.category != "other":
            merged.category = other.category
        merged.recurring = merged.recurring or other.recurring

    srcs: list[str] = []
    names: list[str] = []
    for e in group:
        for s in e.sources:
            if s not in srcs:
                srcs.append(s)
        for n in _names(e):
            if n not in names:
                names.append(n)
    merged.sources = srcs
    merged.source_name = ",".join(names)
    merged.confidence = max(e.confidence for e in group)
    merged.date = min(e.date for e in group)
    ends = [e.end_date for e in group if e.end_date]
    merged.end_date = max(ends) if ends else None

    flyer = ""
    for e in ranked:
        if e.flyer_path and any(n.startswith("ig:") for n in _names(e)):
            flyer = e.flyer_path
            break
    if not flyer:
        flyer = next((e.flyer_path for e in ranked if e.flyer_path), "")
    merged.flyer_path = flyer
    return merged


def dedupe(events: list[Event]) -> list[Event]:
    n = len(events)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(n):
        for j in range(i + 1, n):
            if _same(events[i], events[j]):
                parent[find(j)] = find(i)

    groups: dict[int, list[Event]] = {}
    for i, e in enumerate(events):
        groups.setdefault(find(i), []).append(e)
    return [_merge(g) if len(g) > 1 else g[0] for g in groups.values()]


def unique_counts(events_by_source: dict[str, list[Event]]) -> dict[str, int]:
    """Per source: events with no match in any other source."""
    out: dict[str, int] = {}
    for src, evs in events_by_source.items():
        others = [e for s, es in events_by_source.items() if s != src for e in es]
        out[src] = sum(1 for e in evs if not any(_same(e, o) for o in others))
    return out
