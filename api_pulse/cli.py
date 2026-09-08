from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path

import httpx

from .aggregate import (
    History,
    SanityError,
    check_catalog_sanity,
    check_run_sanity,
    compute_status,
    merge_history,
)
from .fetch import fetch_readme
from .models import ApiEntry, ProbeResult
from .parse import parse_readme
from .probe import probe_all

HISTORY_WINDOW = 90


def _load_history(path: Path) -> History:
    if not path.exists():
        return History(window=HISTORY_WINDOW)
    raw = json.loads(path.read_text(encoding="utf-8"))
    return History(
        window=raw.get("window", HISTORY_WINDOW),
        days=raw.get("days", []),
        entries=raw.get("entries", {}),
    )


def _last_good_count(path: Path) -> int | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8")).get("count")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=1, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )


def run(
    data_dir: Path,
    readme: str,
    results_provider,
    today: date | None = None,
) -> int:
    """Parse, probe, aggregate and write.

    Both circuit breakers run before any file is touched, so a tripped run
    leaves previously good data exactly as it was.
    """
    data_dir = Path(data_dir)
    today = today or datetime.now(timezone.utc).date()

    entries: list[ApiEntry] = parse_readme(readme)
    check_catalog_sanity(len(entries), _last_good_count(data_dir / "catalog.json"))

    results: list[ProbeResult] = results_provider(entries)
    check_run_sanity(results)

    history = merge_history(
        _load_history(data_dir / "history.json"), results, today, window=HISTORY_WINDOW
    )
    statuses = compute_status(entries, results, history)

    generated = today.isoformat()
    _write_json(
        data_dir / "catalog.json",
        {"generated": generated, "count": len(entries), "entries": [asdict(e) for e in entries]},
    )
    _write_json(
        data_dir / "status.json",
        {"generated": generated, "entries": [asdict(s) for s in statuses]},
    )
    _write_json(
        data_dir / "history.json",
        {"generated": generated, "window": history.window, "days": history.days,
         "entries": history.entries},
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

    provider = _live_probe
    if args.limit:
        provider = lambda entries: _live_probe(entries[: args.limit])  # noqa: E731

    try:
        count = run(args.data_dir, fetch_readme(), provider)
    except SanityError as exc:
        print(f"SANITY CHECK FAILED: {exc}")
        return 1

    print(f"wrote {count} entries to {args.data_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
