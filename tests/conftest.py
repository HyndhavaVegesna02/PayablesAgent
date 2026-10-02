"""No test makes a network connection (batch 2 plan, CHG-004 AC8; PO policy:
Gemini costs money and no test may call it). Any connect to a non-loopback
address fails the test that tried it, whatever library made the call."""

from __future__ import annotations

import ipaddress
import socket

import pytest

_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex
_real_getaddrinfo = socket.getaddrinfo


class NetworkBlocked(RuntimeError):
    pass


def _loopback(host) -> bool:
    if host in ("localhost", "testserver", "", None):
        return True
    try:
        return ipaddress.ip_address(str(host).split("%")[0]).is_loopback
    except ValueError:
        return False


def _check(address):
    if isinstance(address, tuple) and address and not _loopback(address[0]):
        raise NetworkBlocked(f"tests may not open network connections (tried {address!r})")


def _connect(self, address):
    if self.family in (socket.AF_INET, socket.AF_INET6):
        _check(address)
    return _real_connect(self, address)


def _connect_ex(self, address):
    if self.family in (socket.AF_INET, socket.AF_INET6):
        _check(address)
    return _real_connect_ex(self, address)


def _getaddrinfo(host, *args, **kwargs):
    if not _loopback(host):
        raise NetworkBlocked(f"tests may not resolve network hosts (tried {host!r})")
    return _real_getaddrinfo(host, *args, **kwargs)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", _connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", _getaddrinfo)
