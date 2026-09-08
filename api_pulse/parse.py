from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from typing import NamedTuple

from .models import ApiEntry

_HEADING_RE = re.compile(r"^###\s+(?P<category>.+?)\s*$")

# A data row: | [Name](url) | description | auth | https | cors |
_ROW_RE = re.compile(
    r"^\|\s*\[(?P<name>[^\]]+)\]\((?P<url>[^)\s]+)\)\s*\|(?P<rest>.*)\|\s*$"
)

_SLUG_STRIP_RE = re.compile(r"[^a-z0-9]+")


class _ParsedRow(NamedTuple):
    """Intermediate row representation before ID assignment."""
    name: str
    url: str
    description: str
    category: str
    auth: str
    https: bool
    cors: str
    base_id: str


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
    edited and always contains some. Callers detect a genuine format break
    by comparing entry counts across runs, not by this function raising.
    """
    # Pass 1: collect all rows and parse
    rows: list[_ParsedRow] = []
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

        rows.append(
            _ParsedRow(
                name=row.group("name").strip(),
                url=row.group("url").strip(),
                description=description,
                category=category,
                auth=_normalise_auth(auth),
                https=https.strip().lower().startswith("yes"),
                cors=_normalise_cors(cors),
                base_id=base_id,
            )
        )

    # Pass 2: count base_id collisions and assign final IDs
    base_id_counts: dict[str, int] = defaultdict(int)
    for row in rows:
        base_id_counts[row.base_id] += 1

    # Track URL-based suffix generation for order-independent collision handling
    base_id_to_urls: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        if base_id_counts[row.base_id] > 1:
            base_id_to_urls[row.base_id].append(row.url)

    # Track which (base_id, url) pairs need fallback encounter-order suffixes
    url_counts: dict[tuple[str, str], int] = defaultdict(int)

    entries: list[ApiEntry] = []
    for row in rows:
        if base_id_counts[row.base_id] == 1:
            # Unique base_id: no suffix needed
            final_id = row.base_id
        else:
            # Collision: use hash-based suffix or fallback encounter-order
            url_counts[(row.base_id, row.url)] += 1
            if url_counts[(row.base_id, row.url)] > 1:
                # Same base_id and URL appear multiple times: use encounter-order
                suffix = str(url_counts[(row.base_id, row.url)])
                final_id = f"{row.base_id}-{suffix}"
            else:
                # Different URLs with same base_id: use hash suffix
                url_hash = hashlib.sha256(row.url.encode("utf-8")).hexdigest()[:6]
                final_id = f"{row.base_id}--{url_hash}"

        entries.append(
            ApiEntry(
                id=final_id,
                name=row.name,
                url=row.url,
                description=row.description,
                category=row.category,
                auth=row.auth,
                https=row.https,
                cors=row.cors,
            )
        )

    return entries
