from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

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

# At most this many vanished categories are named in a SanityError message,
# so a pathological run cannot produce an unreadable GitHub issue body.
MAX_NAMED_CATEGORIES = 5


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

    Days on which the pipeline did not run are filled with NO_DATA_CHAR rather
    than closed up. One column is one calendar day, so the window means 90 days
    and not 90 runs, and a failing streak can never span days nobody measured.
    This is not hypothetical: a packaging fault stopped six consecutive runs in
    September 2026, and closing that gap would have let the pipeline declare
    entries dead on evidence it never gathered.
    """
    today_iso = today.isoformat()
    replacing_today = bool(history.days) and history.days[-1] == today_iso

    days = list(history.days)
    if replacing_today:
        days = days[:-1]

    gap = 0
    if days:
        last = date.fromisoformat(days[-1])
        # max(0, ...) absorbs a clock that goes backwards; a negative gap would
        # otherwise desynchronise every series from the day labels.
        gap = max(0, (today - last).days - 1)
        days.extend((last + timedelta(days=i)).isoformat() for i in range(1, gap + 1))

    length = len(days)
    gap_fill = NO_DATA_CHAR * gap
    merged: dict[str, str] = {}

    for result in results:
        series = history.entries.get(result.entry_id, "")
        if replacing_today and series:
            series = series[:-1]
        # The gap goes on the END: the entry existed, we just did not look.
        # Padding goes on the FRONT: a short series is an entry too young to
        # have existed then. Conflating the two silently reorders the series.
        series = series + gap_fill
        if len(series) > length:
            series = series[len(series) - length :]
        series = series.rjust(length, NO_DATA_CHAR)
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


def check_category_continuity(
    new_ids: set[str],
    last_good_ids_by_category: dict[str, set[str]] | None,
) -> None:
    """Trip if any category from the last good run lost *every* one of its ids.

    Entry IDs embed the category slug, so renaming "### Animals" to
    "### Animals & Pets" re-mints all 26 ids beneath it. History is keyed
    purely by ID, so those 26 series are dropped, every affected entry is
    backfilled with no-data and `likely_dead` resets to False — while the
    catalogue count is unchanged and nothing else notices.

    A GLOBAL churn ratio cannot see this. The largest category in the real
    catalogue is Development at 159 of 1752 entries — 9.1% — so no
    single-category rename can move a global overlap below 90%. Measured on
    the pinned snapshot, the three worst renames score 90.9%, 94.6% and
    98.5% overlap; all three would sail through. The signal is not "how many
    ids changed" but "did a whole category disappear at once".

    So the rule is per-category: every category that existed last run must
    still have at least one surviving id. A rename empties the old category
    completely and trips. The only other way to trip is a genuine upstream
    category deletion — which orphans exactly the same history, so pausing
    for a human is right there too.

    A catalogue that collapses outright is `check_catalog_sanity`'s job, and
    `run()` calls that first.
    """
    if not last_good_ids_by_category:
        # None: first ever run. Empty: nothing to compare against either.
        return

    vanished = sorted(
        category
        for category, ids in last_good_ids_by_category.items()
        if ids and not (ids & new_ids)
    )
    if not vanished:
        return

    def describe(category: str) -> str:
        count = len(last_good_ids_by_category[category])
        return f"{category!r} ({count} entr{'y' if count == 1 else 'ies'})"

    named = ", ".join(describe(c) for c in vanished[:MAX_NAMED_CATEGORIES])
    if len(vanished) > MAX_NAMED_CATEGORIES:
        named += f", and {len(vanished) - MAX_NAMED_CATEGORIES} more"

    plural = "y" if len(vanished) == 1 else "ies"
    raise SanityError(
        f"category churn: {len(vanished)} categor{plural} from the last good "
        f"run lost every entry id: {named}. Upstream probably renamed or "
        f"removed the heading; writing would orphan that history. "
        f"Refusing to write"
    )
