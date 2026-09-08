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

These files are committed daily and are free to use. A run whose circuit
breakers trip writes nothing, so on those days nothing is committed — check the
`generated` field before treating the data as fresh.

## What this measures

The URLs upstream are documentation and homepage links, **not API endpoints**.
API Pulse therefore measures link and domain health, not whether an API
actually works. An entry can be reachable while its API is long dead.

An entry is only marked `likely_dead` after three consecutive failing days, so
a transient outage does not produce a false alarm.

Three circuit breakers guard the published files, and a tripped run writes
nothing at all rather than committing something misleading: the catalogue
shrinking sharply, more than half of all entries failing at once, or a whole
category losing every one of its entry IDs between runs. That last one matters
to consumers — entry IDs embed the upstream category name, so renaming a
category heading re-mints every ID beneath it and would orphan those entries'
history while leaving the total entry count untouched. When that happens the
pipeline **pauses updates** and opens an issue quoting the failure, which names
the affected category, instead of silently resetting every affected series to
zero days of data.

A paused pipeline stays paused: it re-runs and re-fails every day until someone
acts, so `generated` stops advancing. If the upstream change was legitimate —
a category genuinely renamed — the fix is a one-off edit to the published data,
after which the next run proceeds normally:

- **To keep the history:** in `data/history.json` and `data/catalog.json`,
  re-key the affected entries from the old category slug to the new one
  (`animals--cat-facts` → `animals-pets--cat-facts` for a rename of *Animals*
  to *Animals & Pets*), updating each entry's `category` field too. Commit.
- **To accept the loss:** delete `data/catalog.json`. With no baseline both the
  catalogue and continuity breakers stand down for one run and the catalogue
  re-seeds. The renamed entries restart their series, backfilled with `.` for
  the days they existed under the old ID; the old IDs are dropped rather than
  left behind.

## Data format

All three files carry `"schema": 1` and a `"generated"` date. `catalog.json`
and `status.json` join on `id`; `history.json` is a map keyed by the same `id`.

`state` — the outcome of the latest probe. The first four count as **alive**;
every other value counts as a failure for the `failing_streak` filter.

| `state` | Char | Meaning |
|---|---|---|
| `live` | `L` | 2xx or 3xx — the link resolves |
| `auth_required` | `A` | 401 or 403 — gatekeeping correctly, so alive |
| `rate_limited` | `R` | 429 — alive and busy |
| `client_error` | `C` | any other 4xx (400, 405, 451…) — the server answered |
| `not_found` | `N` | 404 or 410 — the link itself is dead |
| `server_error` | `S` | 5xx |
| `tls_invalid` | `T` | certificate could not be verified |
| `dns_failure` | `D` | the hostname does not resolve |
| `unreachable` | `U` | DNS resolved but the connection was refused or reset |
| `timeout` | `X` | no response within 10s |

`history.entries[id]` is one character per day, oldest first, using the Char
column above plus `.` for a day with no data (entry not yet listed, or the run
did not happen). Its length always equals that of `history.days`.

`status.json` entries add: `failing_streak` (consecutive trailing failing days,
which `.` resets), `likely_dead` (`failing_streak >= 3`), `tls_valid`
(`true`/`false`/`null` when not applicable), `cors_header` (the raw
`Access-Control-Allow-Origin` value, or `null`), `final_url` (after redirects),
`response_ms` and `status_code`.

## Probing policy

One concurrent request per host, 20 globally, 10s timeout, one retry, once per
day. `HEAD` first, falling back to `GET` only when the server rejects `HEAD`
with 405 or 501. Requests identify themselves as
`api-pulse/1.0 (+https://github.com/eorgantzoglou/api-pulse)` and send an
`Origin: https://api-pulse.pages.dev` header, which is what makes the
`cors_header` field observable. To have a domain excluded, open an issue.

## Development

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
pytest
python -m api_pulse.cli --data-dir /tmp/api-pulse-scratch --limit 25
```

The scratch directory matters: `--limit` truncates the catalogue itself, so a
limited run against the published `data/` trips the catalogue circuit breaker
by design (`catalogue shrank from 1752 to 25 entries`) and exits 1 rather than
overwriting real data with a 25-entry slice.

## Licence

[MIT](LICENSE).
