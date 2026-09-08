from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ProbeState(StrEnum):
    LIVE = "live"
    AUTH_REQUIRED = "auth_required"
    RATE_LIMITED = "rate_limited"
    CLIENT_ERROR = "client_error"
    NOT_FOUND = "not_found"
    SERVER_ERROR = "server_error"
    TLS_INVALID = "tls_invalid"
    DNS_FAILURE = "dns_failure"
    UNREACHABLE = "unreachable"
    TIMEOUT = "timeout"


class TransportError(StrEnum):
    DNS = "dns"
    TLS = "tls"
    TIMEOUT = "timeout"
    CONNECTION = "connection"


# States that prove the domain is alive. Everything else counts as a failure
# for the flap filter.
ALIVE_STATES: frozenset[ProbeState] = frozenset(
    {
        ProbeState.LIVE,
        ProbeState.AUTH_REQUIRED,
        ProbeState.RATE_LIMITED,
        ProbeState.CLIENT_ERROR,
    }
)

# One character per state, for the compact history encoding.
STATE_CHAR: dict[ProbeState, str] = {
    ProbeState.LIVE: "L",
    ProbeState.AUTH_REQUIRED: "A",
    ProbeState.RATE_LIMITED: "R",
    ProbeState.CLIENT_ERROR: "C",
    ProbeState.NOT_FOUND: "N",
    ProbeState.SERVER_ERROR: "S",
    ProbeState.TLS_INVALID: "T",
    ProbeState.DNS_FAILURE: "D",
    ProbeState.UNREACHABLE: "U",
    ProbeState.TIMEOUT: "X",
}

# Placeholder for a day on which an entry was not probed.
NO_DATA_CHAR = "."

CHAR_STATE: dict[str, ProbeState] = {c: s for s, c in STATE_CHAR.items()}


@dataclass(frozen=True)
class ApiEntry:
    id: str
    name: str
    url: str
    description: str
    category: str
    auth: str
    https: bool
    cors: str


@dataclass(frozen=True)
class ProbeResult:
    entry_id: str
    state: ProbeState
    status_code: int | None = None
    final_url: str | None = None
    response_ms: int | None = None
    tls_valid: bool | None = None
    cors_header: str | None = None
