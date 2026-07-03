"""SMTP host SSRF guard.

A tenant office user can point ``TenantEmailConfig.smtp_host`` at an
arbitrary host that the backend then opens an SMTP connection to (see
``apps.shared.tenants.email_service.EmailService``). Left unchecked, that
host could be an internal / loopback / link-local address — letting a
compromised office account probe internal reachability or reach a cloud
metadata endpoint (``169.254.169.254``) from the backend host (SSRF).

``smtp_host_is_blocked(host)`` resolves a candidate host and returns True
when ANY resolved IP falls in a private / loopback / link-local / reserved
/ multicast / unspecified range. It is used in two places:

  * write-time, in ``TenantEmailConfigSerializer.validate_smtp_host``, so
    the office save is rejected with a clean field error before the host is
    persisted, and
  * send-time, in ``EmailService._get_connection`` — the authoritative
    guard that defends the live production send paths and any
    already-persisted config. (Re-checking at send time also narrows the
    validate-then-resolve-differently / DNS-rebinding window; the residual
    TOCTOU between this check and ``smtplib``'s own resolution can't be
    fully closed without pinning the IP, which would break TLS hostname
    verification — disproportionate for this surface.)

Empty / ``None`` hosts are never blocked: ``smtp_host`` is ``blank=True``
and an unset host means "use the platform default backend" — a trusted,
operator-configured host, not a tenant-supplied target.

The block is gated on ``settings.SMTP_ALLOW_PRIVATE_HOSTS`` (defaults to
``DEBUG``) so local development and tests — which legitimately send through
``localhost`` / MailHog on a private container IP — are unaffected, while
production (``DEBUG=False``) is strict. BYO-SMTP targets are therefore
restricted to public hosts in production; an operator running a legitimate
internal relay can opt back in with ``SMTP_ALLOW_PRIVATE_HOSTS=true``.

A host that fails to resolve is NOT reported as blocked — it can't be an
SSRF target if it doesn't resolve, and the real SMTP connection (with its
timeout) surfaces the DNS error. This avoids rejecting a legitimate public
host over a transient DNS hiccup.

Accepted residual: name resolution itself (``socket.getaddrinfo``) is not
time-bounded by ``EMAIL_TIMEOUT`` (which only caps the SMTP connect). An
office user could PATCH a host whose nameserver stalls and tie up a worker
for the OS resolver timeout. The office-only permission gate keeps this
low-risk; bounding DNS would need a global ``setdefaulttimeout`` or a
threaded resolver, disproportionate here.
"""

from __future__ import annotations

import ipaddress
import socket

from django.conf import settings

_IpAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


def _is_blocked_ip(ip: _IpAddress) -> bool:
    """True when *ip* is in a range an SMTP target must never point at."""
    # An IPv4-mapped IPv6 address (``::ffff:127.0.0.1``) can slip past the
    # IPv6 predicates on some Python versions — unwrap and re-check the
    # embedded IPv4 address.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return (
        ip.is_private  # RFC1918 (10/8, 172.16/12, 192.168/16) + IPv6 ULA
        or ip.is_loopback  # 127.0.0.0/8, ::1
        or ip.is_link_local  # 169.254.0.0/16 (incl. cloud metadata), fe80::/10
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified  # 0.0.0.0, ::
    )


def _resolve_ips(host: str) -> list[_IpAddress]:
    """Return every IP *host* resolves to (a single-element list when it is
    already an IP literal). Raises ``socket.gaierror`` on DNS failure.

    Resolving via ``getaddrinfo`` also normalises sneaky IPv4 encodings
    (decimal ``2130706433``, octal, hex, short ``127.1``) to their canonical
    dotted-quad, so the resolved-IP check below catches them.
    """
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass

    addresses: list[_IpAddress] = []
    # Resolve every A / AAAA record so a multi-record round-robin can't
    # sneak a single private address past the check.
    for info in socket.getaddrinfo(host, None):
        sockaddr = info[4]
        addresses.append(ipaddress.ip_address(sockaddr[0]))
    return addresses


def smtp_host_is_blocked(host) -> bool:
    """Return True when *host* must NOT be used as an SMTP target.

    Empty / ``None`` -> False (platform default, trusted). When
    ``settings.SMTP_ALLOW_PRIVATE_HOSTS`` is set -> always False
    (dev/test escape hatch). A host that resolves to at least one
    private/loopback/link-local/reserved/multicast/unspecified address
    -> True. An unresolvable host -> False (the real connection will fail).
    """
    if host in (None, ""):
        return False
    if getattr(settings, "SMTP_ALLOW_PRIVATE_HOSTS", False):
        return False

    candidate = str(host).strip()
    if not candidate:
        return False
    # A bracketed IPv6 literal ("[::1]") — strip the brackets before parsing.
    if candidate.startswith("[") and candidate.endswith("]"):
        candidate = candidate[1:-1]

    try:
        resolved = _resolve_ips(candidate)
    except (socket.gaierror, UnicodeError, ValueError):
        # Can't resolve / malformed: not provably an internal target, and
        # the actual SMTP connect (with its timeout) will surface the error.
        return False

    return any(_is_blocked_ip(ip) for ip in resolved)
