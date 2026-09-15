import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from api_pulse.aggregate import SanityError
from api_pulse.cli import main, run
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
    assert not (tmp_path / "catalog.json").exists()
    assert not (tmp_path / "status.json").exists()
    assert not (tmp_path / "history.json").exists()


def test_a_failed_run_leaves_previous_data_untouched(tmp_path: Path):
    run(tmp_path, README, all_live, today=date(2026, 9, 1))
    before = {
        name: (tmp_path / name).read_text()
        for name in ("catalog.json", "status.json", "history.json")
    }

    with pytest.raises(SanityError):
        run(tmp_path, README, all_dead, today=date(2026, 9, 2))

    for name, content in before.items():
        assert (tmp_path / name).read_text() == content


def test_a_collapsed_catalogue_trips_the_breaker(tmp_path: Path):
    run(tmp_path, README, all_live, today=date(2026, 9, 1))

    shrunk = """### Animals

API | Description | Auth | HTTPS | CORS
|---|---|---|---|---|
| [Cat Facts](https://catfact.ninja/) | Daily cat facts | No | Yes | No |
"""
    with pytest.raises(SanityError, match="catalogue"):
        run(tmp_path, shrunk, all_live, today=date(2026, 9, 2))


def test_a_limited_run_against_populated_data_trips_the_breaker(tmp_path: Path):
    # A --limit run against a catalogue that already has good data on disk
    # necessarily parses far fewer entries than the last good count, so the
    # catalog-shrink breaker must trip rather than silently erasing the
    # history of every entry the limited run didn't touch.
    run(tmp_path, README, all_live, today=date(2026, 9, 1))
    before = {
        name: (tmp_path / name).read_text()
        for name in ("catalog.json", "status.json", "history.json")
    }

    with pytest.raises(SanityError, match="catalogue"):
        run(tmp_path, README, all_live, today=date(2026, 9, 2), limit=1)

    for name, content in before.items():
        assert (tmp_path / name).read_text() == content


def test_a_limited_run_against_an_empty_data_dir_works_normally(tmp_path: Path):
    written = run(tmp_path, README, all_live, today=date(2026, 9, 1), limit=1)
    assert written == 1
    catalog = json.loads((tmp_path / "catalog.json").read_text())
    assert catalog["count"] == 1
    status = json.loads((tmp_path / "status.json").read_text())
    assert len(status["entries"]) == 1


def test_a_partial_write_failure_leaves_previous_data_untouched(
    tmp_path: Path, monkeypatch
):
    run(tmp_path, README, all_live, today=date(2026, 9, 1))
    before = {
        name: (tmp_path / name).read_text()
        for name in ("catalog.json", "status.json", "history.json")
    }

    original_write_text = Path.write_text
    calls = {"n": 0}

    def flaky_write_text(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("simulated disk failure")
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", flaky_write_text)

    with pytest.raises(OSError):
        run(tmp_path, README, all_live, today=date(2026, 9, 2))

    for name, content in before.items():
        assert (tmp_path / name).read_text() == content
    assert list(tmp_path.glob("*.tmp")) == []


DATA_FILES = ("catalog.json", "status.json", "history.json")


def test_all_three_payloads_declare_their_schema_version(tmp_path: Path):
    run(tmp_path, README, all_live, today=date(2026, 9, 1))
    for name in DATA_FILES:
        payload = json.loads((tmp_path / name).read_text())
        assert payload["schema"] == 1, name


TABLE_HEADER = "API | Description | Auth | HTTPS | CORS\n|---|---|---|---|---|\n"


def multi_category_readme(animals_heading: str = "Animals") -> str:
    """A catalogue whose smallest category is well under 10% of all entries.

    The earlier version of this test used the two-entry, single-category
    README above, so renaming its only category changed 100% of the ids and
    a global-ratio breaker passed it. That gave false confidence: no real
    single-category rename can move a global ratio at all, because the
    largest real category is 9.1% of the catalogue.

    Here Animals is 2 of 32 entries, so renaming it leaves ~94% of ids
    intact — comfortably inside any sane global threshold, and therefore a
    test that only a per-category check can pass.
    """
    parts = [f"### {animals_heading}\n\n", TABLE_HEADER]
    for i in range(2):
        parts.append(
            f"| [Animal {i}](https://animal{i}.example/) | An animal | No | Yes | Yes |\n"
        )
    parts.append("\n### Weather\n\n")
    parts.append(TABLE_HEADER)
    for i in range(30):
        parts.append(
            f"| [Weather {i}](https://weather{i}.example/) | Forecast | No | Yes | Yes |\n"
        )
    return "".join(parts)


def catalog_ids(tmp_path: Path) -> set[str]:
    payload = json.loads((tmp_path / "catalog.json").read_text())
    return {e["id"] for e in payload["entries"]}


def test_a_category_rename_trips_the_continuity_breaker(tmp_path: Path):
    # Every id embeds the category slug, so renaming one heading re-mints
    # every id beneath it. The entry COUNT is unchanged, so the catalogue
    # breaker cannot see this; without this breaker the run would commit a
    # full history reset for the whole category and look perfectly healthy.
    readme = multi_category_readme()
    run(tmp_path, readme, all_live, today=date(2026, 9, 1))
    before = {name: (tmp_path / name).read_bytes() for name in DATA_FILES}
    old_ids = catalog_ids(tmp_path)

    renamed = multi_category_readme("Animals & Pets")

    # Pin the premise: the GLOBAL id overlap stays high, so a ratio-based
    # breaker with any sane threshold would wave this through. This assertion
    # is what makes the test fail if the check ever reverts to a global ratio.
    from api_pulse.parse import parse_readme

    new_ids = {e.id for e in parse_readme(renamed)}
    overlap = len(old_ids & new_ids) / len(old_ids)
    assert overlap > 0.9, f"fixture no longer exercises the case: {overlap:.2%}"

    with pytest.raises(SanityError, match="Animals"):
        run(tmp_path, renamed, all_live, today=date(2026, 9, 2))

    after = {name: (tmp_path / name).read_bytes() for name in DATA_FILES}
    assert after == before
    assert list(tmp_path.glob("*.tmp")) == []


def test_a_deleted_category_trips_the_continuity_breaker(tmp_path: Path):
    # Dropping the two Animals rows keeps 30 of 32 entries, so the catalogue
    # breaker (90% floor) passes it. Their history would be orphaned anyway.
    run(tmp_path, multi_category_readme(), all_live, today=date(2026, 9, 1))
    before = {name: (tmp_path / name).read_bytes() for name in DATA_FILES}

    weather_only = multi_category_readme().split("### Weather", 1)[1]
    with pytest.raises(SanityError, match="Animals"):
        run(tmp_path, "### Weather" + weather_only, all_live, today=date(2026, 9, 2))

    after = {name: (tmp_path / name).read_bytes() for name in DATA_FILES}
    assert after == before


def test_a_growing_catalogue_does_not_trip_the_continuity_breaker(tmp_path: Path):
    # Adding a whole new category while keeping the old ones must be routine.
    run(tmp_path, multi_category_readme(), all_live, today=date(2026, 9, 1))

    grown = multi_category_readme() + "\n### Books\n\n" + TABLE_HEADER
    grown += "| [A Book](https://book.example/) | A book | No | Yes | Yes |\n"
    run(tmp_path, grown, all_live, today=date(2026, 9, 2))

    catalog = json.loads((tmp_path / "catalog.json").read_text())
    assert catalog["count"] == 33


def test_an_unchanged_catalogue_does_not_trip_the_continuity_breaker(tmp_path: Path):
    run(tmp_path, README, all_live, today=date(2026, 9, 1))
    run(tmp_path, README, all_live, today=date(2026, 9, 2))
    history = json.loads((tmp_path / "history.json").read_text())
    assert history["entries"]["animals--cat-facts"] == "LL"


# --- main(): the operator-facing surface -------------------------------


def _stub_main(monkeypatch, readme=README, provider=all_live):
    """Point main() at in-memory data. Nothing here touches the network."""
    import api_pulse.cli as cli_module

    monkeypatch.setattr(cli_module, "fetch_readme", lambda *a, **k: readme)
    monkeypatch.setattr(cli_module, "_live_probe", provider)


def test_main_returns_zero_and_reports_on_success(tmp_path, monkeypatch, capsys):
    _stub_main(monkeypatch)
    assert main(["--data-dir", str(tmp_path)]) == 0
    assert "wrote 2 entries" in capsys.readouterr().out
    assert (tmp_path / "catalog.json").exists()


def test_main_returns_one_and_names_the_breaker_on_a_sanity_failure(
    tmp_path, monkeypatch, capsys
):
    _stub_main(monkeypatch, provider=all_dead)
    assert main(["--data-dir", str(tmp_path)]) == 1
    assert "SANITY CHECK FAILED" in capsys.readouterr().out


def test_main_returns_one_without_a_traceback_on_a_corrupt_catalog(
    tmp_path, monkeypatch, capsys
):
    # A torn or hand-edited catalog.json used to escape main() as a raw
    # JSONDecodeError traceback in an unattended CI log.
    run(tmp_path, README, all_live, today=date(2026, 9, 1))
    (tmp_path / "catalog.json").write_text("{not json", encoding="utf-8")

    _stub_main(monkeypatch)
    assert main(["--data-dir", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert out.startswith("FAILED: JSONDecodeError")


def test_main_returns_one_without_a_traceback_on_a_corrupt_history(
    tmp_path, monkeypatch, capsys
):
    run(tmp_path, README, all_live, today=date(2026, 9, 1))
    (tmp_path / "history.json").write_text("]", encoding="utf-8")

    _stub_main(monkeypatch)
    assert main(["--data-dir", str(tmp_path)]) == 1
    assert "FAILED: JSONDecodeError" in capsys.readouterr().out


def test_main_returns_one_when_fetching_the_readme_fails(
    tmp_path, monkeypatch, capsys
):
    import api_pulse.cli as cli_module

    def boom(*a, **k):
        raise httpx.ConnectError("upstream unreachable")

    monkeypatch.setattr(cli_module, "fetch_readme", boom)
    assert main(["--data-dir", str(tmp_path)]) == 1
    assert "FAILED: ConnectError" in capsys.readouterr().out
    assert not (tmp_path / "catalog.json").exists()


# --- the documented remediation for a legitimate upstream rename -------
#
# README.md tells an operator how to un-pause the pipeline after a real
# category rename. Both routes are pinned here: a documented recovery
# procedure that quietly stops working is worse than none at all, because
# the person following it is already dealing with a broken pipeline.


def test_deleting_the_catalog_unblocks_a_legitimate_rename(tmp_path: Path):
    """README route 2: accept the history loss, re-seed from scratch."""
    run(tmp_path, multi_category_readme(), all_live, today=date(2026, 9, 1))
    renamed = multi_category_readme("Animals & Pets")

    with pytest.raises(SanityError):
        run(tmp_path, renamed, all_live, today=date(2026, 9, 2))

    # The documented action: remove the baseline both breakers read.
    (tmp_path / "catalog.json").unlink()

    written = run(tmp_path, renamed, all_live, today=date(2026, 9, 3))
    assert written == 32
    history = json.loads((tmp_path / "history.json").read_text())
    # history.json survives, so the re-minted ids are backfilled with no-data
    # for the days they did not exist under that id — they do not start a
    # clean one-character series. That is the accepted cost of this route.
    #
    # Three columns, not two: 9-1 ran, 9-2 tripped the breaker and wrote
    # nothing, 9-3 ran. The day a run failed is a real day with no measurement
    # and now holds a column of its own, rather than being closed up as though
    # it never happened.
    assert history["entries"]["animals-pets--animal-0"] == "..L"
    assert len(history["days"]) == 3
    # The orphaned old ids are dropped rather than accumulating: merge_history
    # keeps only entries present in the current run.
    assert "animals--animal-0" not in history["entries"]
    # The untouched category keeps its real series, with the same no-data
    # column for the day the breaker stopped the run.
    assert history["entries"]["weather--weather-0"] == "L.L"


def test_rekeying_the_data_preserves_history_across_a_rename(tmp_path: Path):
    """README route 1: re-key the affected ids and keep the 90-day series."""
    run(tmp_path, multi_category_readme(), all_live, today=date(2026, 9, 1))
    assert json.loads((tmp_path / "history.json").read_text())["entries"][
        "animals--animal-0"
    ] == "L"

    renamed = multi_category_readme("Animals & Pets")
    with pytest.raises(SanityError):
        run(tmp_path, renamed, all_live, today=date(2026, 9, 2))

    # The documented action: rewrite the old category slug to the new one in
    # both files, carrying each entry's series across with it.
    def rekey(entry_id: str) -> str:
        return entry_id.replace("animals--", "animals-pets--", 1)

    catalog = json.loads((tmp_path / "catalog.json").read_text())
    for entry in catalog["entries"]:
        if entry["category"] == "Animals":
            entry["id"] = rekey(entry["id"])
            entry["category"] = "Animals & Pets"
    (tmp_path / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")

    history = json.loads((tmp_path / "history.json").read_text())
    history["entries"] = {rekey(k): v for k, v in history["entries"].items()}
    (tmp_path / "history.json").write_text(json.dumps(history), encoding="utf-8")

    # The next run now proceeds, and the series is continuous across the
    # rename rather than restarting.
    run(tmp_path, renamed, all_live, today=date(2026, 9, 2))
    after = json.loads((tmp_path / "history.json").read_text())
    assert after["entries"]["animals-pets--animal-0"] == "LL"
    assert after["days"] == ["2026-09-01", "2026-09-02"]
