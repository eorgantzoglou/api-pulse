from __future__ import annotations

from .models import ProbeState, TransportError

_ERROR_STATES: dict[TransportError, ProbeState] = {
    TransportError.DNS: ProbeState.DNS_FAILURE,
    TransportError.TLS: ProbeState.TLS_INVALID,
    TransportError.TIMEOUT: ProbeState.TIMEOUT,
    TransportError.CONNECTION: ProbeState.UNREACHABLE,
}


def classify(status_code: int | None, error: TransportError | None) -> ProbeState:
    """Map one probe outcome onto a ProbeState.

    Pure: no network, no clock, no I/O. A transport error always wins, because
    if the transport failed any status code we think we have is meaningless.
    """
    if error is not None:
        return _ERROR_STATES[error]

    if status_code is None:
        return ProbeState.UNREACHABLE

    if 200 <= status_code < 400:
        return ProbeState.LIVE
    if status_code in (401, 403):
        return ProbeState.AUTH_REQUIRED
    if status_code == 429:
        return ProbeState.RATE_LIMITED
    if status_code in (404, 410):
        return ProbeState.NOT_FOUND
    if 400 <= status_code < 500:
        return ProbeState.CLIENT_ERROR
    return ProbeState.SERVER_ERROR
