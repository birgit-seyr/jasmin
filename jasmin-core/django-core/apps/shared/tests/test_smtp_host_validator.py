"""Tests for the SMTP host SSRF guard (``smtp_host_is_blocked``).

Covers which address ranges are blocked (private / loopback / link-local /
cloud-metadata / unspecified / IPv4-mapped IPv6) and the
``SMTP_ALLOW_PRIVATE_HOSTS`` dev/test escape hatch.

IP literals are used for the range cases so no DNS lookup happens; the
hostname-resolution path is exercised with a mocked ``getaddrinfo`` so the
suite stays network-free and deterministic.

The ``@override_settings`` lives on each method, not the class: as a class
decorator it only accepts ``django.test.SimpleTestCase`` subclasses and
raises at collection for a plain pytest class. The default test env runs
``DEBUG=True`` (so ``SMTP_ALLOW_PRIVATE_HOSTS`` defaults True), hence the
explicit ``False`` override is load-bearing for the blocking assertions.
"""

from __future__ import annotations

import socket
from unittest.mock import patch

import pytest
from django.test import override_settings

from apps.shared.smtp_host_validator import smtp_host_is_blocked

BLOCKED_LITERALS = [
    "127.0.0.1",  # IPv4 loopback
    "10.0.0.1",  # RFC1918
    "172.16.5.4",  # RFC1918
    "192.168.1.1",  # RFC1918
    "169.254.169.254",  # link-local — cloud metadata endpoint
    "0.0.0.0",  # unspecified
    "::1",  # IPv6 loopback
    "[::1]",  # bracketed IPv6 loopback
    "::ffff:127.0.0.1",  # IPv4-mapped IPv6 loopback
    "::ffff:10.0.0.1",  # IPv4-mapped IPv6 private
    "fe80::1",  # IPv6 link-local
    "fc00::1",  # IPv6 unique-local (private)
    "224.0.0.1",  # multicast
]

PUBLIC_LITERALS = ["8.8.8.8", "1.1.1.1", "93.184.216.34", "2606:4700:4700::1111"]


class TestBlockedRanges:
    @override_settings(SMTP_ALLOW_PRIVATE_HOSTS=False)
    @pytest.mark.parametrize("host", BLOCKED_LITERALS)
    def test_internal_literal_is_blocked(self, host):
        assert smtp_host_is_blocked(host) is True

    @override_settings(SMTP_ALLOW_PRIVATE_HOSTS=False)
    @pytest.mark.parametrize("host", PUBLIC_LITERALS)
    def test_public_literal_is_allowed(self, host):
        assert smtp_host_is_blocked(host) is False

    @override_settings(SMTP_ALLOW_PRIVATE_HOSTS=False)
    def test_empty_and_none_pass(self):
        # Unset host means "use the platform default backend".
        assert smtp_host_is_blocked(None) is False
        assert smtp_host_is_blocked("") is False
        assert smtp_host_is_blocked("   ") is False

    @override_settings(SMTP_ALLOW_PRIVATE_HOSTS=False)
    def test_hostname_resolving_to_private_is_blocked(self):
        with patch(
            "apps.shared.smtp_host_validator.socket.getaddrinfo",
            return_value=[(socket.AF_INET, 1, 6, "", ("10.1.2.3", 0))],
        ):
            assert smtp_host_is_blocked("smtp.evil.test") is True

    @override_settings(SMTP_ALLOW_PRIVATE_HOSTS=False)
    def test_hostname_resolving_to_public_is_allowed(self):
        with patch(
            "apps.shared.smtp_host_validator.socket.getaddrinfo",
            return_value=[(socket.AF_INET, 1, 6, "", ("93.184.216.34", 0))],
        ):
            assert smtp_host_is_blocked("smtp.example.test") is False

    @override_settings(SMTP_ALLOW_PRIVATE_HOSTS=False)
    def test_mixed_records_block_when_any_is_private(self):
        # A round-robin DNS answer must not let a single private A record by.
        with patch(
            "apps.shared.smtp_host_validator.socket.getaddrinfo",
            return_value=[
                (socket.AF_INET, 1, 6, "", ("93.184.216.34", 0)),
                (socket.AF_INET, 1, 6, "", ("127.0.0.1", 0)),
            ],
        ):
            assert smtp_host_is_blocked("smtp.rebind.test") is True

    @override_settings(SMTP_ALLOW_PRIVATE_HOSTS=False)
    def test_decimal_encoded_ip_normalises_and_is_blocked(self):
        # ``2130706433`` == 127.0.0.1. ``ipaddress`` rejects it, so it falls
        # to getaddrinfo, which normalises to the dotted-quad we then block.
        with patch(
            "apps.shared.smtp_host_validator.socket.getaddrinfo",
            return_value=[(socket.AF_INET, 1, 6, "", ("127.0.0.1", 0))],
        ):
            assert smtp_host_is_blocked("2130706433") is True

    @override_settings(SMTP_ALLOW_PRIVATE_HOSTS=False)
    def test_unresolvable_host_is_not_blocked(self):
        # Can't prove it's internal; the real SMTP connect (with timeout)
        # surfaces the DNS error instead of a false-positive rejection.
        with patch(
            "apps.shared.smtp_host_validator.socket.getaddrinfo",
            side_effect=socket.gaierror("name resolution failed"),
        ):
            assert smtp_host_is_blocked("does-not-exist.test") is False


class TestEscapeHatch:
    @override_settings(SMTP_ALLOW_PRIVATE_HOSTS=True)
    @pytest.mark.parametrize("host", BLOCKED_LITERALS)
    def test_private_allowed_when_flag_set(self, host):
        # Dev / MailHog / localhost: every internal literal passes.
        assert smtp_host_is_blocked(host) is False
