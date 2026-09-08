# API Pulse — Design

Date: 2026-09-08
Status: Approved

## Problem

`github.com/public-apis/public-apis` (~475k stars, MIT) is the best-known index of free
public APIs. Its entire dataset is a single `README.md`: `### Category` headings over
markdown tables of `API | Description | Auth | HTTPS | CORS`, roughly 1,400 entries
across ~50 categories.

The list is static and has no ground truth. It records that an API existed when someone
added it; it never records whether the link still resolves, whether the domain still
exists, or whether the claimed HTTPS/CORS metadata is accurate. Dead entries accumulate
faster than maintainers prune them. Every downstream mirror inherits this defect, because
they all re-render the same static list.

API Pulse adds the missing signal: continuously measured link health, plus a search
interface that can use it.

## Goals

- Publish, and keep publishing without intervention, liveness data for every entry.
- Let a developer filter to APIs that demonstrably still work.
- Surface where the README metadata disagrees with observed reality, in a form that can
  be submitted upstream as a PR.
- Run at zero cost with no server, and survive long periods of total neglect.

## Non-goals

- Verifying that an API *functions*. See "Honesty constraint" below.
- Hosting a queryable backend API. Static JSON files at stable URLs are the interface.
- Replacing or forking public-apis. This is a companion, and corrections flow upstream.

## Honesty constraint

The URLs in the README are documentation/homepage links, not API endpoints. API Pulse
therefore measures **link and domain health**, not whether an API works. An entry can be
reachable while its API is long dead.

This is stated plainly in the UI rather than papered over. It remains the most valuable
signal obtainable without per-API credentials, because domain rot is the dominant way
these entries die.

## Architecture

One public GitHub repository containing two halves that never communicate directly. They
exchange JSON files committed into the repo.

### Pipeline (Python, daily GitHub Actions cron)

1. **fetch** — download `README.md` from
   `raw.githubusercontent.com/public-apis/public-apis/master/`.
2. **parse** — walk `### Category` headings and their tables; emit one record per API
   (name, link, description, category, claimed auth, claimed HTTPS, claimed CORS) to
   `data/catalog.json`.
3. **probe** — request every link; record the observed result.
4. **aggregate** — merge the run into a rolling 90-day history, apply the flap filter,
   write `data/status.json` and `data/history.json`.
5. **embed** — encode name + description + category with a sentence-transformer,
   quantise to int8, write `data/embeddings.bin` and its metadata.
6. **commit** — push changed files to `main`; the static site redeploys automatically.

### Site (static: Cloudflare Pages or GitHub Pages)

Fetches those JSON files and does all filtering, sorting and searching in the browser.
No server exists anywhere in this system.

### Data files

| File | Contents |
|---|---|
| `data/catalog.json` | Current parsed entries and their claimed metadata |
| `data/status.json` | Latest observed result per entry |
| `data/history.json` | Rolling 90-day window, one status byte per entry per day |
| `data/embeddings.bin` | int8-quantised description embeddings |

History is a rolling window rather than a daily full snapshot. 1,400 entries x 90 days is
trivially small, and git history preserves anything older for free. Committing full daily
snapshots would bloat the repository into unusability within a year — unacceptable for a
project expected to run unattended.

All outputs are served at stable URLs (`/data/status.json`, etc.) so other people can
build on them. This costs nothing, since the files already exist.

## The prober

This component sends scheduled traffic to ~1,400 third-party servers. It is a good
citizen by construction, not by intention.

**Politeness, enforced in code:**

- One concurrent request per hostname; global concurrency capped at 20.
- 10-second timeout; one retry with backoff.
- Descriptive `User-Agent` carrying the project URL, so any administrator who sees the
  traffic can identify it and complain.
- `HEAD` first, falling back to `GET` where a server rejects `HEAD`.
- Daily cadence. Faster is rude and yields nothing new. A full run takes roughly 10-15
  minutes, well inside free Actions limits.

**Classification** is a pure function of `(status code, transport error)` returning one of:

| State | Meaning |
|---|---|
| `live` | 2xx/3xx |
| `auth_required` | 401/403 — alive and gatekeeping; **not** a failure |
| `rate_limited` | 429 — also alive |
| `not_found` | 404/410 |
| `server_error` | 5xx |
| `tls_invalid` | Certificate failure |
| `dns_failure` | Name does not resolve |
| `timeout` | No response in budget |

Purity is deliberate: this is the logic most likely to be subtly wrong, and it must be
testable with no network involved.

**Flap filter.** A single failed probe means nothing — runner hiccups, transient 502s,
slow origins. An entry is labelled *likely dead* only after **three consecutive daily
failures**, and the UI shows the failing streak rather than a binary. Without this the
dashboard cries wolf and nobody trusts it; with it, a "dead" label is load-bearing.

**Also recorded per run:** final URL after redirects, response time, TLS validity, and
the `Access-Control-Allow-Origin` header returned when an `Origin` header is sent — which
is what makes checking the README CORS column possible.

## The site

Three views sharing one filter bar: category, auth type, HTTPS, CORS, and a "hide dead
entries" toggle that is **on by default**. That default is the product pitch.

**Browse.** The familiar list, with a 90-day uptime strip, current state and response
time per row. Sortable by reliability.

**Search.** Keyword filtering is instant and always available, running over the
already-loaded catalogue. Semantic search is an **opt-in toggle**, because the embedding
model is a ~20MB download: acceptable as a deliberate, progress-barred cost the user
chose, unacceptable as a surprise on first paint. The browser caches it after the first
load. Queries such as "free weather API, no key, callable from the browser" rank by
meaning while auth/CORS filters apply as hard constraints. With the toggle off the site
is fully functional — the ML is an enhancement, never a dependency.

**Corrections.** Every case where claimed metadata disagrees with observation: entries
flagged HTTPS that redirect to HTTP, entries marked CORS-enabled that send no
`Access-Control-Allow-Origin`, entries whose domain has been dead for months. Each row is
actionable as an upstream PR with evidence attached. This view is what makes the project
matter rather than merely exist.

## Failure modes

Because nobody will be watching this run, failure modes get as much design as features.

**The README format will change.** It is a community repo with ~1.8k open PRs; column and
heading conventions drift. The parser has golden-file tests against a pinned README
snapshot, plus a **circuit breaker**: a run parsing fewer than 90% of the last known-good
entry count fails loudly, commits nothing, and opens an issue. A corrupt catalogue
silently overwriting a good one is the worst available outcome, so that path is closed.

**Our network can fail rather than theirs.** If a run observes more than 50% of all
entries failing, that is the runner, not a mass extinction. The run is discarded and never
written to history, so one bad night cannot poison 1,400 uptime records.

**GitHub disables cron workflows in repositories with no activity for 60 days.** This is
the single most likely cause of silent death during a long absence. The daily bot commit
is itself repository activity and should keep the clock reset; GitHub also emails a
warning before disabling. As belt-and-braces, the push uses a long-lived token rather than
the default workflow token, making the activity unambiguous. This is verified once during
implementation rather than discovered later.

## Testing

Testing follows the shape of the risk.

- **Parser** — real TDD, golden-file tests against a pinned README snapshot, including
  malformed-table and missing-column cases.
- **Classifier** — pure function, exhaustively unit-tested across status codes and
  transport errors.
- **Probe layer** — tested against a fake HTTP client; concurrency and per-host limits
  asserted, no real network in tests.
- **Aggregation** — flap filter and circuit breaker tested directly, including the
  50%-failure discard path.
- **Frontend** — light smoke test. It is a renderer over JSON; correctness lives upstream.

## Build order

Each phase is independently useful and independently shippable.

1. **Pipeline through to `status.json`** — fetch, parse, probe, aggregate, plus the
   Actions cron and the safety rails. At the end of this phase the data exists and is
   updating daily, with no site at all. This is the phase that carries all the risk.
2. **Static site: browse and corrections** — the product becomes visible and useful.
   Keyword search only.
3. **Semantic search** — embedding generation in the pipeline, opt-in client-side model
   in the site. Purely additive; the site works without it.

## Success criteria

- The dashboard reports fresh data with no human intervention for 30 consecutive days.
- Every entry in the catalogue carries a current state and a 90-day history strip.
- The corrections view yields at least one accepted upstream PR to public-apis.
- The site is fully usable with semantic search disabled.
- Total running cost is zero.
