"""CSP violation report endpoint.

Browsers POST a JSON body to this URL whenever a directive in the
`Content-Security-Policy[-Report-Only]` header is violated. We log the
report and return 204. No data is persisted.

The endpoint is mounted on BOTH the tenant and public URL confs because
the CSP header is set by nginx for every server block; we want to receive
reports regardless of which host the violation occurred on.

Logging tag: `csp.violation` (filterable in security.log).
"""

from __future__ import annotations

import json
import logging

from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

logger = logging.getLogger("django.security")

# Cap on body size we're willing to read into memory (defence against junk
# POSTs to the unauthenticated endpoint). 64 KB is generous for a report.
# Reached via ``request.read(...)``, never ``request.body``: the latter
# materialises the WHOLE upload first (DATA_UPLOAD_MAX_MEMORY_SIZE is 50 MB
# here), which would make this cap decorative. Nothing else on this path
# touches ``request.body``, so the stream is still ours to read.
_MAX_REPORT_BYTES = 64 * 1024

# A browser posts ONE violation per request, so a longer array is not a real
# user agent. Without a cap, one anonymous POST of a 64 KB `[{},{},…]` body
# writes ~20k warning lines and rolls the container's whole log-retention
# window — evicting the auth / lockout / authz records an incident responder
# needs, from an endpoint that requires no credentials.
_MAX_REPORTS_PER_POST = 10


@csrf_exempt
@require_POST
def csp_report_view(request: HttpRequest) -> HttpResponse:
    try:
        declared_length = int(request.META.get("CONTENT_LENGTH") or 0)
    except ValueError:
        declared_length = 0  # unparseable header: the bounded read below still caps us
    if declared_length > _MAX_REPORT_BYTES:
        return HttpResponse(status=204)

    raw = request.read(_MAX_REPORT_BYTES)
    try:
        payload = json.loads(raw.decode("utf-8", errors="replace"))
    except (ValueError, UnicodeDecodeError):
        logger.warning(
            "csp.violation.malformed ip=%s host=%s ua=%r",
            request.META.get("REMOTE_ADDR", "?"),
            request.get_host(),
            request.META.get("HTTP_USER_AGENT", "")[:200],
        )
        return HttpResponse(status=204)

    # Browsers may send either the legacy {"csp-report": {...}} envelope or
    # the new Reporting API array. Normalise to a list of dicts.
    # Every entry has to be an object before the reads below: this endpoint is
    # unauthenticated, so a body like {"csp-report": "x"} is one hand-crafted
    # POST away and must not become a 500.
    reports: list[dict] = []
    if isinstance(payload, dict) and isinstance(payload.get("csp-report"), dict):
        reports = [payload["csp-report"]]
    elif isinstance(payload, list):
        reports = [
            report
            for report in (r.get("body", r) for r in payload if isinstance(r, dict))
            if isinstance(report, dict)
        ]

    if len(reports) > _MAX_REPORTS_PER_POST:
        logger.warning(
            "csp.violation.truncated count=%d kept=%d ip=%s",
            len(reports),
            _MAX_REPORTS_PER_POST,
            request.META.get("REMOTE_ADDR", "?"),
        )
        reports = reports[:_MAX_REPORTS_PER_POST]

    for r in reports:
        logger.warning(
            "csp.violation host=%s directive=%r blocked=%r src=%r ip=%s",
            request.get_host(),
            r.get("violated-directive") or r.get("effectiveDirective"),
            r.get("blocked-uri") or r.get("blockedURL"),
            r.get("source-file") or r.get("sourceFile"),
            request.META.get("REMOTE_ADDR", "?"),
        )

    return HttpResponse(status=204)
