"""`infrastructure.security.dns_target_resolver.resolve_and_authorize` —
fail-closed DNS resolution + SSRF authorization (dast-scanner design D3).

`resolver` is injected (mocked `socket.getaddrinfo`-shaped callable) so
these tests never touch a real network or DNS server.
"""

from __future__ import annotations

import asyncio

import pytest

from orchestrator.domain.services.target_url_policy import InvalidTargetUrlError
from orchestrator.infrastructure.security.dns_target_resolver import (
    TargetResolutionError,
    resolve_and_authorize,
)


def _addrinfo(*ips: str) -> list[tuple[int, int, int, str, tuple[object, ...]]]:
    return [(2, 1, 6, "", (ip, 80)) for ip in ips]


def test_resolve_and_authorize_returns_url_when_every_address_is_public() -> None:
    def fake_resolver(
        host: str, port: object
    ) -> list[tuple[int, int, int, str, tuple[object, ...]]]:
        assert host == "example.com"
        return _addrinfo("8.8.8.8", "1.1.1.1")

    result = asyncio.run(resolve_and_authorize("http://example.com", resolver=fake_resolver))
    assert result == "http://example.com"


def test_resolve_and_authorize_raises_on_resolver_error() -> None:
    def failing_resolver(
        host: str, port: object
    ) -> list[tuple[int, int, int, str, tuple[object, ...]]]:
        raise OSError("nodename nor servname provided, or not known")

    with pytest.raises(TargetResolutionError):
        asyncio.run(resolve_and_authorize("http://example.com", resolver=failing_resolver))


def test_resolve_and_authorize_raises_on_zero_addresses() -> None:
    def empty_resolver(
        host: str, port: object
    ) -> list[tuple[int, int, int, str, tuple[object, ...]]]:
        return []

    with pytest.raises(TargetResolutionError):
        asyncio.run(resolve_and_authorize("http://example.com", resolver=empty_resolver))


def test_resolve_and_authorize_raises_if_any_resolved_address_is_blocked() -> None:
    """One public + one blocked address MUST still raise — ANY blocked
    address fails closed, not ALL."""

    def mixed_resolver(
        host: str, port: object
    ) -> list[tuple[int, int, int, str, tuple[object, ...]]]:
        return _addrinfo("8.8.8.8", "127.0.0.1")

    with pytest.raises(TargetResolutionError):
        asyncio.run(resolve_and_authorize("http://example.com", resolver=mixed_resolver))


def test_resolve_and_authorize_raises_on_blocked_ipv6_address() -> None:
    def resolver(host: str, port: object) -> list[tuple[int, int, int, str, tuple[object, ...]]]:
        return _addrinfo("fe80::1")

    with pytest.raises(TargetResolutionError):
        asyncio.run(resolve_and_authorize("http://example.com", resolver=resolver))


def test_resolve_and_authorize_re_validates_shape_before_resolving() -> None:
    """Userinfo is rejected by shape validation before the resolver is ever
    called — a resolver that raises if invoked proves this."""

    def exploding_resolver(
        host: str, port: object
    ) -> list[tuple[int, int, int, str, tuple[object, ...]]]:
        raise AssertionError("resolver must not be called for a shape-invalid URL")

    with pytest.raises(InvalidTargetUrlError):
        asyncio.run(
            resolve_and_authorize("http://user:pass@example.com", resolver=exploding_resolver)
        )
