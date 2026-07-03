import logging

from django.db import connection
from django.http import JsonResponse
from django_tenants.utils import get_public_schema_name

logger = logging.getLogger(__name__)


class TenantActiveMiddleware:
    """Reject requests against a deactivated tenant (operator kill-switch).

    ``Tenant.is_active`` is the deactivation control an operator flips for
    offboarding, non-payment, or a breach. django-tenants resolves the
    schema purely by domain, so without this gate a tenant an operator
    believes is disabled stays fully operational — its users keep logging
    in, refreshing tokens, and calling every API. This turns the flag into
    real enforcement: while it's False, every request against that tenant's
    schema gets a 403, so even already-issued access tokens stop working.

    IMPORTANT — deactivation is a REVERSIBLE PAUSE, not session revocation. It
    does NOT invalidate outstanding refresh cookies or bump any token epoch; on
    reactivation, any refresh token still inside ``REFRESH_TOKEN_LIFETIME``
    (7 days) resumes minting fresh access tokens with no forced re-auth. For the
    dominant cases (non-payment hold, offboarding) that pause-and-resume is the
    intended behaviour. For breach containment, deactivation alone is NOT enough
    — also rotate credentials and force tenant-user password resets (a true hard
    kill would need a per-tenant token epoch in the refresh claims, a migration
    not done here).

    Ordering (see ``settings.MIDDLEWARE``): placed AFTER
    ``TenantMainMiddleware`` (which sets ``request.tenant`` + the schema)
    and AFTER ``CorsMiddleware`` (so the 403 still carries CORS headers and
    the SPA can read the coded body). The public/platform schema is never
    gated — ``Tenant.is_active`` is a per-tenant concept and the
    super-admin platform must stay reachable to flip the flag back.
    ``OPTIONS`` preflight passes through so CORS negotiation isn't broken.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method != "OPTIONS":
            tenant = getattr(request, "tenant", None)
            if (
                tenant is not None
                and connection.schema_name != get_public_schema_name()
                and not getattr(tenant, "is_active", True)
            ):
                logger.warning(
                    "tenant.deactivated.blocked schema=%s path=%s",
                    connection.schema_name,
                    request.path,
                )
                return JsonResponse(
                    {
                        "code": "tenant.deactivated",
                        "message": (
                            "This organization is currently deactivated. "
                            "Please contact support."
                        ),
                    },
                    status=403,
                )
        return self.get_response(request)
