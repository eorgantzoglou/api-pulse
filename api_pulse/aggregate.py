from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .models import (
    ALIVE_STATES,
    CHAR_STATE,
    NO_DATA_CHAR,
    STATE_CHAR,
    ApiEntry,
    ProbeResult,
    ProbeState,
)

# Consecutive failing days before an entry is called dead. Tuned to absorb
# transient outages and runner hiccups; lowering it produces false alarms.
DEAD_AFTER_FAILURES = 3

# A run parsing fewer than this fraction of the last good catalogue means the
# upstream format broke.
MIN_CATALOG_RATIO = 0.9

# A run failing more than this fraction is our network, not theirs.
MAX_RUN_FAILURE_RATIO = 0.5


class SanityError(RuntimeError):
    """A circuit breaker tripped. The caller must write nothing."""


@dataclass
class History:
    window: int
    days: list[str] = field(default_factory=list)
    entries: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class EntryStatus:
    id: str
    state: ProbeState
    status_code: int | None
    final_url: str | None
    response_ms: int | None
    tls_valid: bool | None
    cors_header: str | None
    failing_streak: int
    likely_dead: bool
    history: str


def merge_history(
    history: History,
    results: list[ProbeResult],
    today: date,
    window: int = 90,
) -> History:
    """Append today's results to the rolling window.

    Re-running on a day already recorded overwrites it rather than appending,
    so a manual re-run never distorts the series. Entries missing from this
    run are dropped: the catalogue is the source of truth for what exists.
    """
    today_iso = today.isoformat()
    replacing_today = bool(history.days) and history.days[-1] == today_iso

    days = list(history.days)
    if replacing_today:
        days = days[:-1]

    length = len(days)
    merged: dict[str, str] = {}

    for result in results:
        series = history.entries.get(result.entry_id, "")
        if replacing_today and series:
            series = series[:-1]
        # Backfill a newly-seen entry so every series is the same length.
        series = series[-length:].rjust(length, NO_DATA_CHAR)
        merged[result.entry_id] = series + STATE_CHAR[result.state]

    days.append(today_iso)

    if len(days) > window:
        overflow = len(days) - window
        days = days[overflow:]
        merged = {k: v[overflow:] for k, v in merged.items()}

    return History(window=window, days=days, entries=merged)


def failing_streak(series: str) -> int:
    """Count trailing failure days. Alive states and no-data days end a streak."""
    count = 0
    for char in reversed(series):
        if char == NO_DATA_CHAR:
            break
        state = CHAR_STATE.get(char)
        if state is None or state in ALIVE_STATES:
            break
        count += 1
    return count


def compute_status(
    entries: list[ApiEntry],
    results: list[ProbeResult],
    history: History,
) -> list[EntryStatus]:
    by_id = {r.entry_id: r for r in results}
    statuses: list[EntryStatus] = []

    for entry in entries:
        result = by_id.get(entry.id)
        if result is None:
            continue
        series = history.entries.get(entry.id, "")
        streak = failing_streak(series)
        statuses.append(
            EntryStatus(
                id=entry.id,
                state=result.state,
                status_code=result.status_code,
                final_url=result.final_url,
                response_ms=result.response_ms,
                tls_valid=result.tls_valid,
                cors_header=result.cors_header,
                failing_streak=streak,
                likely_dead=streak >= DEAD_AFTER_FAILURES,
                history=series,
            )
        )

    return statuses


def check_catalog_sanity(new_count: int, last_good_count: int | None) -> None:
    """Trip if the parsed catalogue shrank sharply — the format probably broke."""
    if last_good_count is None:
        return
    if new_count < last_good_count * MIN_CATALOG_RATIO:
        raise SanityError(
            f"catalogue shrank from {last_good_count} to {new_count} entries "
            f"(below {MIN_CATALOG_RATIO:.0%}); refusing to write"
        )


def check_run_sanity(results: list[ProbeResult]) -> None:
    """Trip if most of the internet appears down — almost certainly our runner."""
    if not results:
        raise SanityError("run produced no results; refusing to write")
    failures = sum(1 for r in results if r.state not in ALIVE_STATES)
    ratio = failures / len(results)
    if ratio > MAX_RUN_FAILURE_RATIO:
        raise SanityError(
            f"run failed {ratio:.0%} of {len(results)} entries "
            f"(above {MAX_RUN_FAILURE_RATIO:.0%}); assuming local network fault"
        )
