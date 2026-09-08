import pytest

from api_pulse.classify import classify
from api_pulse.models import ALIVE_STATES, ProbeState, TransportError


@pytest.mark.parametrize(
    "status,expected",
    [
        (200, ProbeState.LIVE),
        (204, ProbeState.LIVE),
        (301, ProbeState.LIVE),
        (302, ProbeState.LIVE),
        (401, ProbeState.AUTH_REQUIRED),
        (403, ProbeState.AUTH_REQUIRED),
        (429, ProbeState.RATE_LIMITED),
        (404, ProbeState.NOT_FOUND),
        (410, ProbeState.NOT_FOUND),
        (400, ProbeState.CLIENT_ERROR),
        (405, ProbeState.CLIENT_ERROR),
        (451, ProbeState.CLIENT_ERROR),
        (500, ProbeState.SERVER_ERROR),
        (503, ProbeState.SERVER_ERROR),
    ],
)
def test_classifies_status_codes(status, expected):
    assert classify(status, None) == expected


@pytest.mark.parametrize(
    "error,expected",
    [
        (TransportError.DNS, ProbeState.DNS_FAILURE),
        (TransportError.TLS, ProbeState.TLS_INVALID),
        (TransportError.TIMEOUT, ProbeState.TIMEOUT),
        (TransportError.CONNECTION, ProbeState.UNREACHABLE),
    ],
)
def test_classifies_transport_errors(error, expected):
    assert classify(None, error) == expected


def test_transport_error_wins_over_status_code():
    # A transport failure means any status code we think we have is meaningless.
    assert classify(200, TransportError.TIMEOUT) == ProbeState.TIMEOUT


def test_no_status_and_no_error_is_unreachable():
    assert classify(None, None) == ProbeState.UNREACHABLE


def test_auth_required_counts_as_alive():
    # A gatekeeping API is working correctly, not broken.
    assert classify(401, None) in ALIVE_STATES
    assert classify(429, None) in ALIVE_STATES
    assert classify(400, None) in ALIVE_STATES


def test_not_found_is_not_alive():
    assert classify(404, None) not in ALIVE_STATES
