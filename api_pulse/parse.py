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

    return _assign_ids(rows)


def _assign_ids(rows: list[_ParsedRow]) -> list[ApiEntry]:
    """Turn collected rows into entries, minting order-independent IDs.

    A base_id produced by exactly one row keeps its clean form. A base_id
    produced by several rows gives every one of them a URL-derived suffix —
    including the first, since leaving that one bare would put the outcome
    back at the mercy of row order.

    A `used` set is the final gate: no id is ever handed out twice, whatever
    route produced it. The counter fallback builds on the *hashed* id rather
    than the bare base_id, so a fallback id can never collide with the clean
    id of an unrelated row whose name happens to end in that number (e.g. two
    "Cats" rows on one URL plus a genuine "Cats 2" row).
    """
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        counts[row.base_id] += 1

    used: set[str] = set()
    entries: list[ApiEntry] = []

    for row in rows:
        entry_id = row.base_id
        if counts[row.base_id] > 1:
            digest = hashlib.sha256(row.url.encode("utf-8")).hexdigest()[:6]
            entry_id = f"{row.base_id}--{digest}"

        # Same name AND same URL: the hash cannot separate them. Fall back to
        # a counter on the hashed id. Both point at one API, so splicing their
        # history is harmless.
        candidate, suffix = entry_id, 1
        while candidate in used:
            suffix += 1
            candidate = f"{entry_id}-{suffix}"
        used.add(candidate)

        entries.append(
            ApiEntry(
                id=candidate,
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
