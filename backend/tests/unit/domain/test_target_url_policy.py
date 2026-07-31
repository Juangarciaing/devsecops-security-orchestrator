"""`domain.services.target_url_policy` — pure DAST target URL validation
(dast-scanner design D3).

Two responsibilities, both framework-free and DNS-free (no `socket` calls —
that's `infrastructure.security.dns_target_resolver`'s job, PR3 task 3.3+):
`validate_target_url_shape` rejects a malformed/dangerous URL shape at
registration time (UX only, no live-attacker guarantee, since a hostname
isn't resolved here); `is_blocked_ip` is the pure CIDR predicate the DNS
resolver re-runs against every resolved address immediately before launch
(the actual SSRF guardrail).
"""

from __future__ import annotations

import ipaddress

import pytest

from orchestrator.domain.services.target_url_policy import (
    InvalidTargetUrlError,
    is_blocked_ip,
    validate_target_url_shape,
)


@pytest.mark.parametrize(
    ("ip_literal", "expected_blocked"),
    [
        # v4 — one representative per named CIDR, plus explicit callouts
        ("0.0.0.0", True),  # 0.0.0.0/8
        ("0.255.255.255", True),
        ("10.0.0.1", True),  # 10/8
        ("100.64.0.1", True),  # 100.64/10 (RFC6598)
        ("100.127.255.255", True),
        ("127.0.0.1", True),  # 127/8
        ("169.254.0.1", True),  # 169.254/16
        ("169.254.169.254", True),  # cloud metadata endpoint, explicit
        ("172.16.0.1", True),  # 172.16/12
        ("172.31.255.255", True),
        ("192.0.0.1", True),  # 192.0.0/24
        ("192.168.1.1", True),  # 192.168/16
        ("198.18.0.1", True),  # 198.18/15
        ("198.19.255.255", True),
        ("224.0.0.1", True),  # 224/4
        ("240.0.0.1", True),  # 240/4
        ("255.255.255.255", True),
        ("8.8.8.8", False),  # public
        ("1.1.1.1", False),  # public
        # v6
        ("::", True),  # ::/128
        ("::1", True),  # ::1/128
        ("fc00::1", True),  # fc00::/7 (ULA)
        ("fd00::1", True),
        ("fe80::1", True),  # fe80::/10
        ("ff00::1", True),  # ff00::/8
        ("64:ff9b::1", True),  # NAT64
        ("2001:4860:4860::8888", False),  # public
        # IPv4-mapped v6: unwrap-and-recheck, never a blanket block
        ("::ffff:127.0.0.1", True),
        ("::ffff:8.8.8.8", False),
    ],
)
def test_is_blocked_ip_table(ip_literal: str, expected_blocked: bool) -> None:
    assert is_blocked_ip(ipaddress.ip_address(ip_literal)) is expected_blocked


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://example.com/path?query=1",
        "http://sub.example.com:8080/",
    ],
)
def test_validate_target_url_shape_accepts_well_formed_hostname_urls(url: str) -> None:
    result = validate_target_url_shape(url)
    assert result.url == url


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "example.com",  # no scheme
    ],
)
def test_validate_target_url_shape_rejects_non_http_scheme(url: str) -> None:
    with pytest.raises(InvalidTargetUrlError):
        validate_target_url_shape(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://user@example.com",
        "http://user:pass@example.com",
    ],
)
def test_validate_target_url_shape_rejects_userinfo(url: str) -> None:
    with pytest.raises(InvalidTargetUrlError):
        validate_target_url_shape(url)


def test_validate_target_url_shape_rejects_missing_host() -> None:
    with pytest.raises(InvalidTargetUrlError):
        validate_target_url_shape("http://")


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1",
        "http://169.254.169.254/latest/meta-data",
        "https://[::1]/",
    ],
)
def test_validate_target_url_shape_rejects_blocked_ip_literal(url: str) -> None:
    with pytest.raises(InvalidTargetUrlError):
        validate_target_url_shape(url)
