# API Pulse

Liveness data for every entry in [public-apis/public-apis](https://github.com/public-apis/public-apis).

The upstream list records that an API existed when someone added it. It never
records whether the link still resolves. This repository probes all ~1,750
entries daily and publishes the results as JSON.

## Data

| File | Contents |
|---|---|
| [`data/catalog.json`](data/catalog.json) | Parsed entries and their claimed metadata |
| [`data/status.json`](data/status.json) | Latest observed state per entry |
| [`data/history.json`](data/history.json) | Rolling 90-day series, one character per day |

These files are committed daily and are free to use.

## What this measures

The URLs upstream are documentation and homepage links, **not API endpoints**.
API Pulse therefore measures link and domain health, not whether an API
actually works. An entry can be reachable while its API is long dead.

An entry is only marked `likely_dead` after three consecutive failing days, so
a transient outage does not produce a false alarm.

Three circuit breakers guard the published files, and a tripped run writes
nothing at all rather than committing something misleading: the catalogue
shrinking sharply, more than half of all entries failing at once, or too many
entry IDs changing between runs. That last one matters to consumers — entry IDs
embed the upstream category name, so a large upstream restructuring (renaming a
category heading, say) re-mints every ID beneath it and would orphan those
entries' history. When that happens the pipeline **pauses updates** and opens an
issue instead of silently resetting every affected series to zero days of data.

## Probing policy

One concurrent request per host, 20 globally, 10s timeout, one retry, once per
day. Requests identify themselves as
`api-pulse/1.0 (+https://github.com/eorgantzoglou/api-pulse)`.
To have a domain excluded, open an issue.

## Development

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
pytest
python -m api_pulse.cli --data-dir data --limit 25
```

MIT.
