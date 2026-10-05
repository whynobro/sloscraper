"""Listing scrapers. Each source module exposes fetch() -> list[Event] and a pure parse(text)."""
from __future__ import annotations

import logging
from typing import Callable

from ..models import Event
from . import fremont, goslo, hellomorrobay, newtimes

log = logging.getLogger(__name__)

SOURCES: dict[str, Callable[[], list[Event]]] = {
    "goslo": goslo.fetch,
    "fremont": fremont.fetch,
    "hellomorrobay": hellomorrobay.fetch,
    "newtimes": newtimes.fetch,
}


def fetch_all() -> dict[str, list[Event] | Exception]:
    """Run every source; one failure never stops the others."""
    results: dict[str, list[Event] | Exception] = {}
    for name, fn in SOURCES.items():
        try:
            results[name] = fn()
        except Exception as exc:  # noqa: BLE001 - isolation is the point
            log.warning("source %s failed: %r", name, exc)
            results[name] = exc
    return results
