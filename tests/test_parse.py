from pathlib import Path

import pytest

from api_pulse.parse import parse_readme, slugify

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample() -> str:
    return (FIXTURES / "sample_readme.md").read_text(encoding="utf-8")


def test_parses_every_well_formed_row(sample):
    entries = parse_readme(sample)
    assert len(entries) == 3


def test_skips_malformed_rows(sample):
    names = [e.name for e in parse_readme(sample)]
    assert "Broken Row" not in names
    assert "Not A Link" not in names


def test_extracts_all_fields(sample):
    entry = next(e for e in parse_readme(sample) if e.name == "Dog CEO")
    assert entry.url == "https://dog.ceo/dog-api/"
    assert entry.description == "Dog pictures"
    assert entry.category == "Animals"
    assert entry.auth == "apiKey"
    assert entry.https is True
    assert entry.cors == "yes"


def test_normalises_absent_auth_to_empty_string(sample):
    entry = next(e for e in parse_readme(sample) if e.name == "Cat Facts")
    assert entry.auth == ""


def test_normalises_cors_values(sample):
    by_name = {e.name: e for e in parse_readme(sample)}
    assert by_name["Cat Facts"].cors == "no"
    assert by_name["Dog CEO"].cors == "yes"
    assert by_name["Open-Meteo"].cors == "unknown"


def test_ignores_the_index_section(sample):
    # The Index is a bullet list of anchor links, not a table.
    assert all(e.category in {"Animals", "Weather"} for e in parse_readme(sample))


def test_ids_are_stable_and_unique(sample):
    ids = [e.id for e in parse_readme(sample)]
    assert len(ids) == len(set(ids))
    assert parse_readme(sample)[0].id == "animals--cat-facts"


def test_duplicate_names_get_order_independent_url_derived_ids():
    rows = [
        "| [Cats](https://a.example/) | One | No | Yes | Yes |",
        "| [Cats](https://b.example/) | Two | No | Yes | Yes |",
    ]
    header = "### Animals\n\nAPI | Description | Auth | HTTPS | CORS\n|---|---|---|---|---|\n"

    forward = {e.url: e.id for e in parse_readme(header + "\n".join(rows))}
    reversed_ = {e.url: e.id for e in parse_readme(header + "\n".join(reversed(rows)))}

    # The same URL must get the same id no matter where it appears in the file.
    assert forward == reversed_
    assert len(set(forward.values())) == 2
    assert all(i.startswith("animals--cats--") for i in forward.values())


def test_a_unique_name_keeps_a_clean_id():
    markdown = """### Animals

API | Description | Auth | HTTPS | CORS
|---|---|---|---|---|
| [Cats](https://a.example/) | One | No | Yes | Yes |
"""
    assert parse_readme(markdown)[0].id == "animals--cats"


def test_identical_name_and_url_still_yields_unique_ids():
    markdown = """### Animals

API | Description | Auth | HTTPS | CORS
|---|---|---|---|---|
| [Cats](https://a.example/) | One | No | Yes | Yes |
| [Cats](https://a.example/) | Two | No | Yes | Yes |
"""
    ids = [e.id for e in parse_readme(markdown)]
    assert len(set(ids)) == 2


def test_slugify():
    assert slugify("Open-Meteo") == "open-meteo"
    assert slugify("Books & Libraries") == "books-libraries"
    assert slugify("  Spaced  Out  ") == "spaced-out"


def test_empty_input_yields_no_entries():
    assert parse_readme("") == []


def test_real_snapshot_parses_a_plausible_catalogue():
    snapshot = FIXTURES / "readme_snapshot.md"
    entries = parse_readme(snapshot.read_text(encoding="utf-8"))
    # Structural assertions only — exact counts drift as the upstream repo changes.
    assert len(entries) > 1000
    assert len({e.category for e in entries}) > 30
    assert all(e.name and e.url and e.category for e in entries)
    assert all(e.url.startswith("http") for e in entries)
    assert len({e.id for e in entries}) == len(entries)
