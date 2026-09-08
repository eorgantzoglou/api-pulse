import json
from datetime import date
from pathlib import Path

import pytest

from api_pulse.aggregate import SanityError
from api_pulse.cli import run
from api_pulse.models import ProbeResult, ProbeState

README = """### Animals

API | Description | Auth | HTTPS | CORS
|---|---|---|---|---|
| [Cat Facts](https://catfact.ninja/) | Daily cat facts | No | Yes | No |
| [Dog CEO](https://dog.ceo/dog-api/) | Dog pictures | `apiKey` | Yes | Yes |
"""


def all_live(entries):
    return [ProbeResult(entry_id=e.id, state=ProbeState.LIVE, status_code=200) for e in entries]


def all_dead(entries):
    return [ProbeResult(entry_id=e.id, state=ProbeState.TIMEOUT) for e in entries]


def test_writes_all_three_data_files(tmp_path: Path):
    run(tmp_path, README, all_live, today=date(2026, 9, 1))
    assert (tmp_path / "catalog.json").exists()
    assert (tmp_path / "status.json").exists()
    assert (tmp_path / "history.json").exists()


def test_catalog_contains_every_parsed_entry(tmp_path: Path):
    run(tmp_path, README, all_live, today=date(2026, 9, 1))
    catalog = json.loads((tmp_path / "catalog.json").read_text())
    assert catalog["count"] == 2
    assert {e["name"] for e in catalog["entries"]} == {"Cat Facts", "Dog CEO"}


def test_status_carries_liveness_fields(tmp_path: Path):
    run(tmp_path, README, all_live, today=date(2026, 9, 1))
    status = json.loads((tmp_path / "status.json").read_text())
    first = status["entries"][0]
    assert first["state"] == "live"
    assert first["likely_dead"] is False
    assert "failing_streak" in first


def test_history_accumulates_across_runs(tmp_path: Path):
    run(tmp_path, README, all_live, today=date(2026, 9, 1))
    run(tmp_path, README, all_live, today=date(2026, 9, 2))
    history = json.loads((tmp_path / "history.json").read_text())
    assert history["days"] == ["2026-09-01", "2026-09-02"]
    assert history["entries"]["animals--cat-facts"] == "LL"


def test_three_bad_days_marks_entries_dead(tmp_path: Path):
    # A mixed run keeps the run-level breaker from tripping: one entry fails
    # persistently while the other stays up.
    def one_down(entries):
        return [
            ProbeResult(
                entry_id=e.id,
                state=ProbeState.NOT_FOUND if e.id.endswith("cat-facts") else ProbeState.LIVE,
                status_code=404 if e.id.endswith("cat-facts") else 200,
            )
            for e in entries
        ]

    for day in (1, 2, 3):
        run(tmp_path, README, one_down, today=date(2026, 9, day))

    status = json.loads((tmp_path / "status.json").read_text())
    by_id = {e["id"]: e for e in status["entries"]}
    assert by_id["animals--cat-facts"]["likely_dead"] is True
    assert by_id["animals--dog-ceo"]["likely_dead"] is False


def test_a_failed_run_writes_nothing_at_all(tmp_path: Path):
    with pytest.raises(SanityError):
        run(tmp_path, README, all_dead, today=date(2026, 9, 1))
    assert not (tmp_path / "status.json").exists()
    assert not (tmp_path / "history.json").exists()


def test_a_failed_run_leaves_previous_data_untouched(tmp_path: Path):
    run(tmp_path, README, all_live, today=date(2026, 9, 1))
    before = (tmp_path / "status.json").read_text()

    with pytest.raises(SanityError):
        run(tmp_path, README, all_dead, today=date(2026, 9, 2))

    assert (tmp_path / "status.json").read_text() == before


def test_a_collapsed_catalogue_trips_the_breaker(tmp_path: Path):
    run(tmp_path, README, all_live, today=date(2026, 9, 1))

    shrunk = """### Animals

API | Description | Auth | HTTPS | CORS
|---|---|---|---|---|
| [Cat Facts](https://catfact.ninja/) | Daily cat facts | No | Yes | No |
"""
    with pytest.raises(SanityError, match="catalogue"):
        run(tmp_path, shrunk, all_live, today=date(2026, 9, 2))
