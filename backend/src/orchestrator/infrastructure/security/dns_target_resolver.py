"""Fail-closed DNS resolution + SSRF authorization for DAST targets
(dast-scanner design D3).

`resolve_and_authorize` is the actual network-boundary guardrail —
`ZapDastDockerExecution.execute()` (PR5) calls it immediately before its
first `runner.run()`, the narrowest possible check-to-create window.
Registration-time `domain.services.target_url_policy.validate_target_url_
shape` is UX only and never resolves DNS; this is the only place a hostname
is actually resolved and checked, so it re-runs shape validation itself
rather than trusting a caller already did.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable

from orchestrator.domain.services.target_url_policy import (
    is_blocked_ip,
    validate_target_url_shape,
)

_GetAddrInfoResult = list[tuple[int, int, int, str, tuple[object, ...]]]
_GetAddrInfo = Callable[..., _GetAddrInfoResult]


class TargetResolutionError(Exception):
    """Raised when a target URL cannot be safely resolved and authorized."""


async def resolve_and_authorize(url: str, *, resolver: _GetAddrInfo = socket.getaddrinfo) -> str:
    """Re-validate `url`'s shape, resolve its host, and authorize every
    resolved address.

    Fail-closed: raises on a resolver error, on zero resolved addresses, and
    if ANY (not all) resolved A/AAAA is blocked — never proceeds on a
    partial pass. Returns `url` unchanged only once every resolved address
    clears `is_blocked_ip`.
    """
    parsed = validate_target_url_shape(url)

    try:
        addrinfo = resolver(parsed.host, None)
    except OSError as exc:
        raise TargetResolutionError(f"DNS resolution failed for {parsed.host!r}") from exc

    if not addrinfo:
        raise TargetResolutionError(f"DNS resolution returned no addresses for {parsed.host!r}")

    for _family, _type, _proto, _canonname, sockaddr in addrinfo:
        ip = ipaddress.ip_address(sockaddr[0])
        if is_blocked_ip(ip):
            raise TargetResolutionError(f"resolved address {ip} is blocked for {parsed.host!r}")

    return url
