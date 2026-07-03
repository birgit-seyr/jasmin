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
_MAX_REPORT_BYTES = 64 * 1024


@csrf_exempt
@require_POST
def csp_report_view(request: HttpRequest) -> HttpResponse:
    raw = request.body[:_MAX_REPORT_BYTES]
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
    reports: list[dict] = []
    if isinstance(payload, dict) and "csp-report" in payload:
        reports = [payload["csp-report"]]
    elif isinstance(payload, list):
        reports = [r.get("body", r) for r in payload if isinstance(r, dict)]

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
