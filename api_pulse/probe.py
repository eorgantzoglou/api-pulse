from __future__ import annotations

import asyncio
import time
from collections import defaultdict

import httpx

from .classify import classify
from .models import ApiEntry, ProbeResult, ProbeState, TransportError

USER_AGENT = "api-pulse/1.0 (+https://github.com/eorgantzoglou/api-pulse)"
PROBE_ORIGIN = "https://api-pulse.pages.dev"

_HEADERS = {
    "User-Agent": USER_AGENT,
    "Origin": PROBE_ORIGIN,
    "Accept": "*/*",
}


def _transport_error_for(exc: Exception) -> TransportError:
    """Classify an httpx exception into a coarse transport failure kind."""
    if isinstance(exc, httpx.TimeoutException):
        return TransportError.TIMEOUT
    message = str(exc).lower()
    if "certificate" in message or "ssl" in message or "tls" in message:
        return TransportError.TLS
    if "name or service not known" in message or "nodename" in message or "getaddrinfo" in message:
        return TransportError.DNS
    return TransportError.CONNECTION


async def probe_one(client, entry: ApiEntry, timeout: float, backoff: float) -> ProbeResult:
    """Probe a single entry. Never raises — every failure becomes a ProbeResult."""
    started = time.perf_counter()
    error: TransportError | None = None
    response = None

    for attempt in range(2):  # original + exactly one retry
        try:
            response = await client.request(
                "HEAD",
                entry.url,
                headers=_HEADERS,
                timeout=timeout,
                follow_redirects=True,
            )
            # Some servers reject HEAD outright; retry those once with GET.
            if response.status_code in (405, 501):
                response = await client.request(
                    "GET",
                    entry.url,
                    headers=_HEADERS,
                    timeout=timeout,
                    follow_redirects=True,
                )
            error = None
            break
        except Exception as exc:  # noqa: BLE001 - any failure is data, not a crash
            error = _transport_error_for(exc)
            response = None
            if attempt == 0 and backoff:
                await asyncio.sleep(backoff)

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    status_code = response.status_code if response is not None else None
    state = classify(status_code, error)

    if error is TransportError.TLS:
        tls_valid: bool | None = False
    elif response is not None and entry.url.startswith("https"):
        tls_valid = True
    else:
        tls_valid = None

    headers = getattr(response, "headers", {}) or {}

    return ProbeResult(
        entry_id=entry.id,
        state=state,
        status_code=status_code,
        final_url=str(response.url) if response is not None else None,
        response_ms=elapsed_ms,
        tls_valid=tls_valid,
        cors_header=headers.get("access-control-allow-origin"),
    )


async def probe_all(
    entries: list[ApiEntry],
    client,
    *,
    global_limit: int = 20,
    per_host_limit: int = 1,
    timeout: float = 10.0,
    backoff: float = 1.0,
) -> list[ProbeResult]:
    """Probe every entry under strict politeness limits.

    Two nested semaphores: one global cap, and one per hostname so we never
    hit a single stranger's server with concurrent requests.
    """
    global_sem = asyncio.Semaphore(global_limit)
    host_sems: dict[str, asyncio.Semaphore] = defaultdict(
        lambda: asyncio.Semaphore(per_host_limit)
    )

    async def guarded(entry: ApiEntry) -> ProbeResult:
        # Community-edited markdown can contain malformed URLs (bad ports,
        # bad IDNA hosts, ...). httpx.URL() raises on those — never let that
        # escape this function, or one bad row kills the entire gather().
        try:
            host = httpx.URL(entry.url).host or entry.url
        except Exception:
            host = entry.url

        try:
            # Acquire the scarce per-host permit first, the plentiful global
            # permit second. Reversing this lets many tasks for one dead
            # host squat on global permits while blocked on the host lock,
            # starving every other host. This order still has a single
            # global lock ordering (host, then global) so it stays
            # deadlock-free.
            async with host_sems[host]:
                async with global_sem:
                    return await probe_one(client, entry, timeout, backoff)
        except Exception:
            # probe_one already never raises; this is a last-resort net so
            # that even a bug here can't take down the whole run.
            return ProbeResult(entry_id=entry.id, state=ProbeState.UNREACHABLE)

    return await asyncio.gather(*(guarded(e) for e in entries))
