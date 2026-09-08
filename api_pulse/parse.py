from __future__ import annotations

import re

from .models import ApiEntry

_HEADING_RE = re.compile(r"^###\s+(?P<category>.+?)\s*$")

# A data row: | [Name](url) | description | auth | https | cors |
_ROW_RE = re.compile(
    r"^\|\s*\[(?P<name>[^\]]+)\]\((?P<url>[^)\s]+)\)\s*\|(?P<rest>.*)\|\s*$"
)

_SLUG_STRIP_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    return _SLUG_STRIP_RE.sub("-", text.strip().lower()).strip("-")


def _normalise_auth(cell: str) -> str:
    value = cell.strip().strip("`").strip()
    if value.lower() in ("no", "none", ""):
        return ""
    return value


def _normalise_cors(cell: str) -> str:
    value = cell.strip().strip("`").strip().lower()
    return value if value in ("yes", "no") else "unknown"


def parse_readme(markdown: str) -> list[ApiEntry]:
    """Extract one ApiEntry per well-formed table row.

    Malformed rows are skipped silently — the upstream README is community
    edited and always contains some. Callers detect a genuine format break via
    check_catalog_sanity(), not by this function raising.
    """
    entries: list[ApiEntry] = []
    seen_ids: dict[str, int] = {}
    category: str | None = None

    for line in markdown.splitlines():
        heading = _HEADING_RE.match(line)
        if heading:
            category = heading.group("category")
            continue

        if category is None:
            continue

        row = _ROW_RE.match(line)
        if not row:
            continue

        cells = [c.strip() for c in row.group("rest").split("|")]
        if len(cells) < 4:
            continue

        description, auth, https, cors = cells[0], cells[1], cells[2], cells[3]

        base_id = f"{slugify(category)}--{slugify(row.group('name'))}"
        seen_ids[base_id] = seen_ids.get(base_id, 0) + 1
        entry_id = base_id if seen_ids[base_id] == 1 else f"{base_id}-{seen_ids[base_id]}"

        entries.append(
            ApiEntry(
                id=entry_id,
                name=row.group("name").strip(),
                url=row.group("url").strip(),
                description=description,
                category=category,
                auth=_normalise_auth(auth),
                https=https.strip().lower().startswith("yes"),
                cors=_normalise_cors(cors),
            )
        )

    return entries
