from datetime import date
from pathlib import Path

import pytest

from api_pulse.aggregate import (
    DEAD_AFTER_FAILURES,
    History,
    SanityError,
    check_catalog_sanity,
    check_category_continuity,
    check_run_sanity,
    compute_status,
    failing_streak,
    merge_history,
)
from api_pulse.models import ApiEntry, ProbeResult, ProbeState

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def real_snapshot() -> str:
    """The pinned upstream README. Read from disk — never fetched."""
    return (FIXTURES / "readme_snapshot.md").read_text(encoding="utf-8")


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


# --- breaker thresholds, pinned exactly on the boundary ----------------
#
# Both breakers use a strict comparison against a ratio. Nothing else in the
# suite sits on the boundary, so `<` silently becoming `<=` (or `>` becoming
# `>=`) would not fail a single test — on the two rails the whole unattended
# premise rests on.


def test_a_catalogue_exactly_on_the_threshold_is_accepted():
    # 900 == 1000 * 0.9 exactly: not "below", so it must pass.
    check_catalog_sanity(new_count=900, last_good_count=1000)


def test_a_run_failing_exactly_half_is_accepted():
    # 5/10 == 0.5 exactly: not "more than half", so it must pass.
    results = [result(f"e{i}", ProbeState.TIMEOUT) for i in range(5)]
    results += [result(f"ok{i}", ProbeState.LIVE) for i in range(5)]
    check_run_sanity(results)


# --- the category-continuity breaker -----------------------------------
#
# The question this breaker asks is NOT "how many ids changed" but "did a
# whole category disappear at once". Entry ids embed the category slug, so a
# renamed heading re-mints every id beneath it and orphans that history while
# the catalogue count stays put.


def by_category(**categories: int) -> dict[str, set[str]]:
    """Build an id-set-per-category baseline: by_category(Animals=3, ...)."""
    return {
        name: {f"{name.lower()}--e{i}" for i in range(count)}
        for name, count in categories.items()
    }


def flatten(grouped: dict[str, set[str]]) -> set[str]:
    return {i for ids in grouped.values() for i in ids}


def test_first_ever_run_has_no_category_baseline_to_compare_against():
    check_category_continuity({"a", "b", "c"}, None)


def test_an_empty_baseline_is_treated_as_no_baseline():
    check_category_continuity({"a", "b", "c"}, {})


def test_an_unchanged_catalogue_is_accepted():
    baseline = by_category(Animals=3, Weather=4)
    check_category_continuity(flatten(baseline), baseline)


def test_losing_some_but_not_all_of_a_category_is_accepted():
    # Individual entries come and go upstream every week. Only a category
    # emptying completely is the restructuring signal.
    baseline = by_category(Animals=5, Weather=4)
    survivors = flatten(baseline) - {"animals--e0", "animals--e1", "weather--e3"}
    check_category_continuity(survivors, baseline)


def test_a_large_legitimate_addition_is_accepted():
    # Every old category intact, hundreds of new entries and two brand-new
    # categories. Nothing was orphaned, so nothing should trip.
    baseline = by_category(Animals=3, Weather=4)
    new_ids = flatten(baseline)
    new_ids |= {f"animals--new{i}" for i in range(200)}
    new_ids |= {f"blockchain--e{i}" for i in range(150)}
    check_category_continuity(new_ids, baseline)


def test_a_renamed_category_trips_and_names_it():
    baseline = by_category(Animals=26, Weather=40)
    # The rename re-mints every id under Animals and nothing else.
    new_ids = baseline["Weather"] | {f"animals-and-pets--e{i}" for i in range(26)}

    with pytest.raises(SanityError) as excinfo:
        check_category_continuity(new_ids, baseline)

    message = str(excinfo.value)
    # The operator reads this in a GitHub issue months from now; it has to
    # say WHICH category to go and look at.
    assert "Animals" in message
    assert "26 entries" in message
    assert "Weather" not in message


def test_a_deleted_category_trips():
    baseline = by_category(Animals=26, Weather=40)
    with pytest.raises(SanityError, match="Animals"):
        check_category_continuity(baseline["Weather"], baseline)


def test_several_vanished_categories_are_all_named():
    baseline = by_category(Animals=2, Weather=2, Books=2)
    with pytest.raises(SanityError) as excinfo:
        check_category_continuity(baseline["Books"], baseline)
    message = str(excinfo.value)
    assert "Animals" in message and "Weather" in message
    assert "2 categories" in message


def test_a_pathological_run_names_only_the_first_few_categories():
    # Guards the GitHub issue body against an unreadable 51-category dump.
    baseline = by_category(**{f"Cat{i}": 2 for i in range(20)})
    with pytest.raises(SanityError, match="and 15 more"):
        check_category_continuity(set(), baseline)


def test_a_category_rename_trips_even_when_global_id_overlap_stays_high(
    real_snapshot,
):
    """Regression guard for a breaker that measured the wrong thing.

    This check was first specified as a GLOBAL id-overlap ratio with a 90%
    floor. Against the real catalogue that can never fire on a rename: the
    largest category is Development at 159 of 1752 entries (9.1%), so every
    single-category rename leaves overlap above 90% by construction. Renaming
    Animals leaves 98.5%. This test pins that the breaker trips anyway.
    """
    from api_pulse.parse import parse_readme

    old_entries = parse_readme(real_snapshot)
    old_ids = {e.id for e in old_entries}
    baseline: dict[str, set[str]] = {}
    for entry in old_entries:
        baseline.setdefault(entry.category, set()).add(entry.id)

    assert "Animals" in baseline
    renamed = real_snapshot.replace("### Animals", "### Animals & Pets")
    new_ids = {e.id for e in parse_readme(renamed)}

    # The premise: a global ratio would sail straight through this.
    overlap = len(old_ids & new_ids) / len(old_ids)
    assert overlap > 0.9, f"expected a high global overlap, got {overlap:.2%}"

    with pytest.raises(SanityError, match="Animals"):
        check_category_continuity(new_ids, baseline)
