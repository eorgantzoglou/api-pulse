from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections.abc import Callable
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path

import httpx

from .aggregate import (
    History,
    SanityError,
    check_catalog_sanity,
    check_id_churn,
    check_run_sanity,
    compute_status,
    merge_history,
)
from .fetch import fetch_readme
from .models import ApiEntry, ProbeResult
from .parse import parse_readme
from .probe import probe_all

HISTORY_WINDOW = 90

# On-disk format version, stamped into all three payloads. Bump it whenever a
# field changes meaning or disappears, so a consumer can pin to a known shape.
SCHEMA_VERSION = 1


def _load_history(path: Path) -> History:
    """Load the rolling series from disk.

    The on-disk "window" field is deliberately NOT read back. HISTORY_WINDOW
    is the single source of truth for retention, and run() passes it to
    merge_history on every call — so honouring a stale value from the file
    would only let a hand-edited or older history.json quietly change how
    much history the pipeline keeps. The field is written for consumers, and
    merge_history re-stamps it each run.
    """
    if not path.exists():
        return History(window=HISTORY_WINDOW)
    raw = json.loads(path.read_text(encoding="utf-8"))
    return History(
        window=HISTORY_WINDOW,
        days=raw.get("days", []),
        entries=raw.get("entries", {}),
    )


def _last_good_count(path: Path) -> int | None:
    """Read the previous run's entry count from catalog.json.

    Returns None when there is no baseline, which DISABLES the catalogue
    breaker for that run. A catalog.json missing its "count" key therefore
    disables it just as silently as a missing file does — the breaker is
    fail-open by design, because a first run has nothing to compare against.
    """
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8")).get("count")


def _last_good_ids(path: Path) -> set[str] | None:
    """Read the previous run's entry IDs from catalog.json.

    Same fail-open contract as _last_good_count: None means no baseline and
    the churn breaker does not run.
    """
    if not path.exists():
        return None
    entries = json.loads(path.read_text(encoding="utf-8")).get("entries")
    if entries is None:
        return None
    return {e["id"] for e in entries if isinstance(e, dict) and "id" in e}


def _write_all_json(items: list[tuple[Path, dict]]) -> None:
    """Write every payload to a temp file, then promote all of them together.

    Every payload is written to a `<name>.tmp` file alongside its target
    first. Only once *all* of them have been written successfully are the
    originals replaced, one `os.replace` per file (atomic on both Windows
    and POSIX). If any temp write fails, every temp file created so far is
    removed and the original files are left completely untouched — a crash
    or I/O error mid-write can never leave a truncated or mismatched file
    on disk.
    """
    tmp_paths: list[Path] = []
    try:
        for path, payload in items:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = path.with_name(path.name + ".tmp")
            tmp_paths.append(tmp_path)
            tmp_path.write_text(
                json.dumps(payload, indent=1, sort_keys=True, ensure_ascii=False),
                encoding="utf-8",
            )
    except Exception:
        for tmp_path in tmp_paths:
            tmp_path.unlink(missing_ok=True)
        raise

    for (path, _), tmp_path in zip(items, tmp_paths):
        os.replace(tmp_path, path)


def run(
    data_dir: Path,
    readme: str,
    results_provider: Callable[[list[ApiEntry]], list[ProbeResult]],
    today: date | None = None,
    limit: int | None = None,
) -> int:
    """Parse, probe, aggregate and write.

    All three circuit breakers run before any file is touched, so a tripped
    run leaves previously good data exactly as it was. `limit`, when given,
    truncates the parsed catalogue itself (before any breaker runs) so
    that the catalogue, status and history files always describe the same
    set of entries — a development-only `--limit` run never drops the
    history of entries it didn't probe.
    """
    data_dir = Path(data_dir)
    today = today or datetime.now(timezone.utc).date()

    entries: list[ApiEntry] = parse_readme(readme)
    if limit is not None:
        entries = entries[:limit]
    catalog_path = data_dir / "catalog.json"
    check_catalog_sanity(len(entries), _last_good_count(catalog_path))
    check_id_churn({e.id for e in entries}, _last_good_ids(catalog_path))

    results: list[ProbeResult] = results_provider(entries)
    check_run_sanity(results)

    history = merge_history(
        _load_history(data_dir / "history.json"), results, today, window=HISTORY_WINDOW
    )
    statuses = compute_status(entries, results, history)

    generated = today.isoformat()
    _write_all_json(
        [
            (
                data_dir / "catalog.json",
                {
                    "schema": SCHEMA_VERSION,
                    "generated": generated,
                    "count": len(entries),
                    "entries": [asdict(e) for e in entries],
                },
            ),
            (
                data_dir / "status.json",
                {
                    "schema": SCHEMA_VERSION,
                    "generated": generated,
                    "entries": [asdict(s) for s in statuses],
                },
            ),
            (
                data_dir / "history.json",
                {
                    "schema": SCHEMA_VERSION,
                    "generated": generated,
                    "window": history.window,
                    "days": history.days,
                    "entries": history.entries,
                },
            ),
        ]
    )

    return len(entries)


def _live_probe(entries: list[ApiEntry]) -> list[ProbeResult]:
    async def go() -> list[ProbeResult]:
        async with httpx.AsyncClient() as client:
            return await probe_all(entries, client)

    return asyncio.run(go())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="api-pulse")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--limit", type=int, default=None,
                        help="probe only the first N entries (development only)")
    args = parser.parse_args(argv)

    try:
        count = run(args.data_dir, fetch_readme(), _live_probe, limit=args.limit)
    except SanityError as exc:
        print(f"SANITY CHECK FAILED: {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001 - operator-facing surface
        # This process runs unattended for months with nobody watching. A
        # corrupt data file, a full disk or an httpx error must produce one
        # readable line and exit 1, not a raw traceback in a CI log.
        print(f"FAILED: {type(exc).__name__}: {exc}")
        return 1

    print(f"wrote {count} entries to {args.data_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
