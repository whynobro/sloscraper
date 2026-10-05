"""Merge the same event seen in several sources. Pure functions, no I/O."""
from __future__ import annotations

import re
from dataclasses import replace

from rapidfuzz import fuzz

from .models import Event

THRESHOLD = 85
_NOISE = {"live", "presents", "present", "presented", "tickets", "ticket", "w", "with", "by", "the", "and", "feat", "featuring"}
_TRAILING_AT = re.compile(r"\s+(?:at|@)\s+.*$")


def norm_title(s: str) -> str:
    s = (s or "").lower()
    s = _TRAILING_AT.sub("", s)
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


def _same(a: Event, b: Event) -> bool:
    if a.date != b.date or not _towns_compatible(a, b):
        return False
    na, nb = norm_title(a.title), norm_title(b.title)
    if na and nb and fuzz.token_set_ratio(na, nb) >= THRESHOLD:
        return True
    pa, pb = _perf_key(a), _perf_key(b)
    if pa and pb and fuzz.token_set_ratio(pa, pb) >= THRESHOLD:
        return True
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
            if events[i].date == events[j].date and _same(events[i], events[j]):
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
