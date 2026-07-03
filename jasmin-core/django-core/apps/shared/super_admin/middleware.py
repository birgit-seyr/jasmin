"""App-layer IP allowlist for the super-admin platform API.

Defense-in-depth mirror of the nginx gateway allowlist. The gateway restricts
the super-admin *host* to an IP allowlist, but that depends on host routing
staying correct — a routing gap (the apex domain resolving to the public
schema, which mounts ``/api/super-admin/``) could expose the platform-root API
off-allowlist. This middleware enforces the same allowlist inside Django over
the ``/api/super-admin/`` path prefix, so the control no longer depends on
nginx host routing alone.

It covers EVERY super-admin endpoint uniformly — login, refresh, and all
authenticated viewsets — because it gates on the URL path, not a per-view
permission class (which a future endpoint could forget to apply).

Activation is opt-in via ``settings.SUPER_ADMIN_ALLOWED_IPS``:
  * unset / empty  -> no-op (dev, and deployments relying solely on the nginx
    allowlist, are unaffected);
  * set            -> requests under ``/api/super-admin/`` from a client IP not
    in the list get a 403 before reaching any view.

The client IP comes from :func:`apps.shared.request_utils.client_ip`, which
reads the trusted (non-spoofable, nginx-appended) entry ``TRUSTED_PROXY_COUNT``
positions from the right of ``X-Forwarded-For`` — the same value used for
throttle / lockout keying. A client cannot forge an allowed IP by sending a
crafted ``X-Forwarded-For`` header.
"""

from __future__ import annotations

import ipaddress
import logging

from django.conf import settings
from django.http import JsonResponse

from apps.shared.request_utils import client_ip

logger = logging.getLogger("authentication")

SUPER_ADMIN_PATH_PREFIX = "/api/super-admin/"


def _parse_networks(entries) -> list:
    """Parse allowlist strings into ``ip_network`` objects, skipping (with a
    loud log) any malformed entry so one typo can't silently open the gate."""
    networks = []
    for entry in entries or []:
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            logger.error(
                "super_admin.ip_allowlist.invalid_entry entry=%r — ignored; "
                "fix SUPER_ADMIN_ALLOWED_IPS",
                entry,
            )
    return networks


def _ip_in_networks(raw_ip: str, networks: list) -> bool:
    if not raw_ip:
        return False
    try:
        addr = ipaddress.ip_address(raw_ip)
    except ValueError:
        return False
    return any(addr in network for network in networks)


class SuperAdminIPAllowlistMiddleware:
    """Block ``/api/super-admin/`` requests from non-allowlisted client IPs.

    No-op unless ``settings.SUPER_ADMIN_ALLOWED_IPS`` is configured. The
    allowlist is parsed once at startup.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.networks = _parse_networks(
            getattr(settings, "SUPER_ADMIN_ALLOWED_IPS", [])
        )

    def __call__(self, request):
        # Fast path: not configured, or not a super-admin request.
        if self.networks and request.path.startswith(SUPER_ADMIN_PATH_PREFIX):
            ip = client_ip(request)
            if not _ip_in_networks(ip, self.networks):
                logger.warning(
                    "super_admin.ip_allowlist.blocked ip=%s path=%s",
                    ip or "-",
                    request.path,
                )
                return JsonResponse(
                    {
                        "code": "super_admin.ip_not_allowed",
                        "message": "Access to the super-admin API is not "
                        "allowed from this network.",
                    },
                    status=403,
                )
        return self.get_response(request)
