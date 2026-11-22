"""Windows: a connection whose socket shutdown fails still leaves the server's count.

Runs on any OS against the standard library's own proactor code (the module imports
everywhere); only the socket is faked.
"""

import errno
from asyncio import proactor_events

import pytest

from wvw_analyzer.main import detach_closed_sockets


class FakeSocket:
    def __init__(self, shutdown_error: OSError | None):
        self.shutdown_error = shutdown_error
        self.closed = False

    def fileno(self) -> int:
        return -1 if self.closed else 7

    def shutdown(self, how: int) -> None:
        if self.shutdown_error:
            raise self.shutdown_error

    def close(self) -> None:
        self.closed = True


class FakeServer:
    def __init__(self) -> None:
        self.active = 1

    def _detach(self) -> None:
        self.active -= 1


class FakeProtocol:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.lost = 0

    def connection_lost(self, exc: BaseException | None) -> None:
        self.lost += 1
        if self.error:
            raise self.error


def _transport_class() -> type:
    """A stand-in transport using the standard library's _call_connection_lost."""

    class Transport:
        _call_connection_lost = proactor_events._ProactorBasePipeTransport._call_connection_lost

        def __init__(self, sock: FakeSocket, protocol: FakeProtocol) -> None:
            self._sock = sock
            self._server = FakeServer()
            self._protocol = protocol
            self._called_connection_lost = False

    return Transport


WIN_10022 = OSError(errno.EINVAL, "An invalid argument was supplied")


def test_the_standard_cleanup_stops_when_the_socket_shutdown_fails():
    """The bug this works around: the server keeps counting the connection."""
    t = _transport_class()(FakeSocket(WIN_10022), FakeProtocol())
    server = t._server
    with pytest.raises(OSError):
        t._call_connection_lost(None)
    assert server.active == 1 and not t._sock.closed


def test_a_failed_socket_shutdown_still_closes_and_detaches():
    cls = _transport_class()
    detach_closed_sockets(cls)
    sock, protocol = FakeSocket(WIN_10022), FakeProtocol()
    t = cls(sock, protocol)
    server = t._server
    t._call_connection_lost(None)
    assert sock.closed and t._sock is None
    assert server.active == 0 and t._server is None
    assert t._called_connection_lost and protocol.lost == 1
    t._call_connection_lost(None)  # a second call does nothing, as in the standard code
    assert server.active == 0 and protocol.lost == 1


def test_a_normal_close_is_unchanged_and_patching_twice_is_harmless():
    cls = _transport_class()
    detach_closed_sockets(cls)
    detach_closed_sockets(cls)
    t = cls(FakeSocket(None), FakeProtocol())
    server = t._server
    t._call_connection_lost(None)
    assert server.active == 0 and t._sock is None and t._called_connection_lost


def test_an_error_from_the_protocol_is_still_raised():
    cls = _transport_class()
    detach_closed_sockets(cls)
    t = cls(FakeSocket(None), FakeProtocol(OSError("protocol failed")))
    server = t._server
    with pytest.raises(OSError, match="protocol failed"):
        t._call_connection_lost(None)
    assert server.active == 0  # the standard cleanup ran in its `finally`
