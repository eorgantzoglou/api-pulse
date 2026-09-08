import asyncio
from dataclasses import dataclass, field

import httpx
import pytest

from api_pulse.models import ApiEntry, ProbeState
from api_pulse.probe import USER_AGENT, probe_all


def entry(entry_id: str, url: str) -> ApiEntry:
    return ApiEntry(
        id=entry_id,
        name=entry_id,
        url=url,
        description="",
        category="Test",
        auth="",
        https=url.startswith("https"),
        cors="unknown",
    )


@dataclass
class FakeResponse:
    status_code: int
    url: str
    headers: dict = field(default_factory=dict)


@dataclass
class FakeClient:
    """Records calls and replays scripted outcomes keyed by URL."""

    outcomes: dict
    calls: list = field(default_factory=list)
    concurrent: int = 0
    max_concurrent: int = 0
    per_host_peak: dict = field(default_factory=dict)
    _host_active: dict = field(default_factory=dict)

    async def request(self, method, url, **kwargs):
        host = httpx.URL(url).host
        self.concurrent += 1
        self._host_active[host] = self._host_active.get(host, 0) + 1
        self.max_concurrent = max(self.max_concurrent, self.concurrent)
        self.per_host_peak[host] = max(
            self.per_host_peak.get(host, 0), self._host_active[host]
        )
        try:
            await asyncio.sleep(0)  # give the loop a chance to interleave
            self.calls.append((method, url))
            outcome = self.outcomes[url]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        finally:
            self.concurrent -= 1
            self._host_active[host] -= 1


async def test_records_a_live_entry():
    url = "https://a.example/"
    client = FakeClient({url: FakeResponse(200, url, {"access-control-allow-origin": "*"})})
    (result,) = await probe_all([entry("a", url)], client)
    assert result.entry_id == "a"
    assert result.state == ProbeState.LIVE
    assert result.status_code == 200
    assert result.cors_header == "*"
    assert result.tls_valid is True
    assert result.response_ms is not None


async def test_records_the_final_url_after_redirects():
    url = "https://a.example/"
    client = FakeClient({url: FakeResponse(200, "https://a.example/final")})
    (result,) = await probe_all([entry("a", url)], client)
    assert result.final_url == "https://a.example/final"


async def test_maps_a_timeout_to_the_timeout_state():
    url = "https://slow.example/"
    client = FakeClient({url: httpx.ConnectTimeout("too slow")})
    (result,) = await probe_all([entry("a", url)], client)
    assert result.state == ProbeState.TIMEOUT


async def test_maps_tls_failure_and_marks_tls_invalid():
    url = "https://bad-cert.example/"
    client = FakeClient({url: httpx.ConnectError("certificate verify failed")})
    (result,) = await probe_all([entry("a", url)], client)
    assert result.state == ProbeState.TLS_INVALID
    assert result.tls_valid is False


async def test_retries_once_before_giving_up():
    url = "https://flaky.example/"
    client = FakeClient({url: httpx.ConnectTimeout("nope")})
    await probe_all([entry("a", url)], client, backoff=0)
    assert len(client.calls) == 2  # original + one retry


async def test_falls_back_to_get_when_head_is_rejected():
    url = "https://picky.example/"
    client = FakeClient({url: FakeResponse(405, url)})
    (result,) = await probe_all([entry("a", url)], client)
    assert [c[0] for c in client.calls] == ["HEAD", "GET"]


async def test_sends_the_project_user_agent_and_an_origin():
    url = "https://a.example/"
    seen = {}

    class HeaderSpy(FakeClient):
        async def request(self, method, url, **kwargs):
            seen.update(kwargs.get("headers") or {})
            return await super().request(method, url, **kwargs)

    await probe_all([entry("a", url)], HeaderSpy({url: FakeResponse(200, url)}))
    assert seen["User-Agent"] == USER_AGENT
    assert "Origin" in seen


async def test_never_exceeds_the_global_concurrency_limit():
    urls = [f"https://host{i}.example/" for i in range(30)]
    client = FakeClient({u: FakeResponse(200, u) for u in urls})
    await probe_all([entry(u, u) for u in urls], client, global_limit=5)
    assert client.max_concurrent <= 5


async def test_never_makes_two_concurrent_requests_to_one_host():
    urls = [f"https://same.example/{i}" for i in range(10)]
    client = FakeClient({u: FakeResponse(200, u) for u in urls})
    await probe_all([entry(u, u) for u in urls], client, global_limit=20)
    assert client.per_host_peak["same.example"] == 1


async def test_returns_one_result_per_entry():
    urls = [f"https://h{i}.example/" for i in range(5)]
    client = FakeClient({u: FakeResponse(200, u) for u in urls})
    results = await probe_all([entry(u, u) for u in urls], client)
    assert len(results) == 5
    assert {r.entry_id for r in results} == set(urls)
