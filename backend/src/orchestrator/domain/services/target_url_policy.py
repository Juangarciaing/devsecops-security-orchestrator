"""Pure DAST target URL validation (dast-scanner design D3).

Framework-free: this module MUST NOT import SQLAlchemy or Pydantic, and MUST
NOT perform any I/O (no `socket`, no DNS) — `is_blocked_ip` is a pure CIDR
predicate over an already-parsed `ipaddress` object, and
`validate_target_url_shape` only inspects the URL's literal shape.

`is_blocked_ip` is the actual SSRF guardrail: `infrastructure.security.
dns_target_resolver.resolve_and_authorize` re-runs it against every
resolved address immediately before a scan launches. `validate_target_url_
shape` is registration-time UX only — a hostname is not resolved here, so
passing shape validation is not a live-attacker guarantee by itself.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from urllib.parse import urlsplit

#: Explicit CIDR blocklist, ORed with the `ipaddress` built-in predicates
#: (`is_private`/`is_loopback`/`is_link_local`/`is_multicast`/`is_reserved`)
#: — belt-and-suspenders: each range here is individually test-asserted
#: rather than trusting `ipaddress`'s classification alone (design D3).
_BLOCKED_NETWORKS_V4: tuple[ipaddress.IPv4Network, ...] = tuple(
    ipaddress.ip_network(cidr)
    for cidr in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",  # RFC 6598 (CGNAT)
        "127.0.0.0/8",
        "169.254.0.0/16",  # link-local, incl. 169.254.169.254 (cloud metadata)
        "172.16.0.0/12",
        "192.0.0.0/24",
        "192.168.0.0/16",
        "198.18.0.0/15",  # benchmark range
        "224.0.0.0/4",  # multicast
        "240.0.0.0/4",  # reserved
    )
)
_BLOCKED_NETWORKS_V6: tuple[ipaddress.IPv6Network, ...] = tuple(
    ipaddress.ip_network(cidr)
    for cidr in (
        "::/128",
        "::1/128",
        "fc00::/7",  # ULA
        "fe80::/10",  # link-local
        "ff00::/8",  # multicast
        "64:ff9b::/96",  # NAT64
    )
)

_ALLOWED_SCHEMES = frozenset({"http", "https"})


class InvalidTargetUrlError(ValueError):
    """Raised when a target URL's shape is malformed or disallowed."""


@dataclass(frozen=True, slots=True)
class ParsedTarget:
    """A target URL that has passed shape validation."""

    url: str
    host: str


def is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return `True` if `ip` falls in a non-routable/internal/reserved range.

    An IPv4-mapped IPv6 address (e.g. `::ffff:127.0.0.1`) is unwrapped to
    its underlying IPv4 address and re-checked — a classic SSRF-guardrail
    bypass this codebase has no other prior art for. `ip.ipv4_mapped` is
    `None` for every other address, so this is a no-op for anything else.
    """
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return is_blocked_ip(ip.ipv4_mapped)

    if isinstance(ip, ipaddress.IPv4Address):
        return ip.is_private or ip.is_reserved or any(ip in net for net in _BLOCKED_NETWORKS_V4)

    return ip.is_private or ip.is_reserved or any(ip in net for net in _BLOCKED_NETWORKS_V6)


def validate_target_url_shape(url: str) -> ParsedTarget:
    """Reject a malformed/dangerous URL shape at registration time.

    Rejects: a scheme outside `{http, https}`; a missing host; userinfo
    (`user[:pass]@`) present; and a host that is itself a blocked IP
    literal. Does NOT resolve a hostname — that DNS-dependent check is
    `infrastructure.security.dns_target_resolver.resolve_and_authorize`'s
    job, re-run immediately before every scan launch.
    """
    parts = urlsplit(url)

    if parts.scheme not in _ALLOWED_SCHEMES:
        raise InvalidTargetUrlError(f"unsupported scheme: {parts.scheme!r}")
    if not parts.hostname:
        raise InvalidTargetUrlError("target URL has no host")
    if parts.username is not None or parts.password is not None:
        raise InvalidTargetUrlError("target URL must not carry userinfo")

    try:
        host_ip = ipaddress.ip_address(parts.hostname)
    except ValueError:
        host_ip = None
    if host_ip is not None and is_blocked_ip(host_ip):
        raise InvalidTargetUrlError(f"target host is a blocked IP literal: {parts.hostname!r}")

    return ParsedTarget(url=url, host=parts.hostname)
