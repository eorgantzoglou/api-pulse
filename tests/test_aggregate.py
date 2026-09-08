from datetime import date

import pytest

from api_pulse.aggregate import (
    DEAD_AFTER_FAILURES,
    History,
    SanityError,
    check_catalog_sanity,
    check_run_sanity,
    compute_status,
    failing_streak,
    merge_history,
)
from api_pulse.models import ApiEntry, ProbeResult, ProbeState


def entry(entry_id: str) -> ApiEntry:
    return ApiEntry(
        id=entry_id,
        name=entry_id,
        url=f"https://{entry_id}.example/",
        description="",
        category="Test",
        auth="",
        https=True,
        cors="unknown",
    )


def result(entry_id: str, state: ProbeState) -> ProbeResult:
    return ProbeResult(entry_id=entry_id, state=state, status_code=200)


def empty_history() -> History:
    return History(window=90, days=[], entries={})


# --- history merging ---------------------------------------------------


def test_appends_one_character_per_day():
    history = merge_history(empty_history(), [result("a", ProbeState.LIVE)], date(2026, 9, 1))
    assert history.days == ["2026-09-01"]
    assert history.entries["a"] == "L"

    history = merge_history(history, [result("a", ProbeState.NOT_FOUND)], date(2026, 9, 2))
    assert history.days == ["2026-09-01", "2026-09-02"]
    assert history.entries["a"] == "LN"


def test_trims_to_the_rolling_window():
    history = empty_history()
    for day in range(1, 8):
        history = merge_history(
            history, [result("a", ProbeState.LIVE)], date(2026, 9, day), window=5
        )
    assert len(history.days) == 5
    assert len(history.entries["a"]) == 5
    assert history.days[0] == "2026-09-03"


def test_a_brand_new_entry_is_backfilled_with_no_data():
    history = merge_history(empty_history(), [result("a", ProbeState.LIVE)], date(2026, 9, 1))
    history = merge_history(
        history,
        [result("a", ProbeState.LIVE), result("b", ProbeState.LIVE)],
        date(2026, 9, 2),
    )
    assert history.entries["b"] == ".L"
    assert len(history.entries["b"]) == len(history.days)


def test_entries_that_leave_the_catalogue_are_dropped():
    history = merge_history(
        empty_history(),
        [result("a", ProbeState.LIVE), result("gone", ProbeState.LIVE)],
        date(2026, 9, 1),
    )
    history = merge_history(history, [result("a", ProbeState.LIVE)], date(2026, 9, 2))
    assert "gone" not in history.entries


def test_re_running_the_same_day_overwrites_rather_than_appends():
    history = merge_history(empty_history(), [result("a", ProbeState.LIVE)], date(2026, 9, 1))
    history = merge_history(history, [result("a", ProbeState.NOT_FOUND)], date(2026, 9, 1))
    assert history.days == ["2026-09-01"]
    assert history.entries["a"] == "N"


# --- the flap filter ---------------------------------------------------


def test_failing_streak_counts_only_trailing_failures():
    assert failing_streak("LLLNNN") == 3
    assert failing_streak("NNNLLL") == 0
    assert failing_streak("LLLL") == 0
    assert failing_streak("NNNN") == 4
    assert failing_streak("") == 0


def test_alive_states_do_not_count_as_failures():
    # auth_required, rate_limited and client_error all prove the domain lives.
    assert failing_streak("NNAR") == 0
    assert failing_streak("LLLC") == 0


def test_no_data_days_do_not_count_as_failures():
    assert failing_streak("LLL..") == 0


def test_one_failure_is_not_enough_to_call_an_entry_dead():
    history = History(window=90, days=["d1", "d2"], entries={"a": "LN"})
    (status,) = compute_status([entry("a")], [result("a", ProbeState.NOT_FOUND)], history)
    assert status.failing_streak == 1
    assert status.likely_dead is False


def test_three_consecutive_failures_marks_an_entry_likely_dead():
    history = History(window=90, days=["d1", "d2", "d3"], entries={"a": "NNN"})
    (status,) = compute_status([entry("a")], [result("a", ProbeState.NOT_FOUND)], history)
    assert status.failing_streak == DEAD_AFTER_FAILURES
    assert status.likely_dead is True


def test_status_carries_the_history_series_through():
    history = History(window=90, days=["d1", "d2"], entries={"a": "LL"})
    (status,) = compute_status([entry("a")], [result("a", ProbeState.LIVE)], history)
    assert status.history == "LL"
    assert status.state == ProbeState.LIVE


# --- circuit breakers --------------------------------------------------


def test_catalogue_shrinking_past_the_threshold_raises():
    with pytest.raises(SanityError, match="catalogue"):
        check_catalog_sanity(new_count=800, last_good_count=1000)


def test_catalogue_within_the_threshold_is_accepted():
    check_catalog_sanity(new_count=950, last_good_count=1000)
    check_catalog_sanity(new_count=1200, last_good_count=1000)


def test_first_ever_run_has_no_baseline_to_compare_against():
    check_catalog_sanity(new_count=1400, last_good_count=None)


def test_a_run_failing_more_than_half_of_all_entries_raises():
    results = [result(f"e{i}", ProbeState.TIMEOUT) for i in range(6)]
    results += [result(f"ok{i}", ProbeState.LIVE) for i in range(4)]
    with pytest.raises(SanityError, match="run"):
        check_run_sanity(results)


def test_a_normal_failure_rate_is_accepted():
    results = [result(f"e{i}", ProbeState.TIMEOUT) for i in range(2)]
    results += [result(f"ok{i}", ProbeState.LIVE) for i in range(8)]
    check_run_sanity(results)


def test_an_empty_run_raises():
    with pytest.raises(SanityError):
        check_run_sanity([])
