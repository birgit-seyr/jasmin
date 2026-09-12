from __future__ import annotations

from urllib.parse import quote, unquote, urlsplit

from django.conf import settings
from django.db import connection
from django.http import FileResponse, HttpResponse, HttpResponseBase, JsonResponse
from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from core.errors import NotFoundError
from core.protected_media import INTERNAL_MEDIA_LOCATION
from core.serializers import ErrorResponseSerializer

from .errors import NoTenantContext
from .models import Tenant
from .serializers import CurrentTenantSerializer

# Static platform fallback shipped in the frontend's ``public/``. Used until a
# tenant uploads its own icon — an empty ``icons`` array would make the app
# abruptly non-installable, so the manifest always carries exactly one entry.
FALLBACK_APP_ICON_PATH = "/pwa-icon-512.png"

# One day. The icon is immutable branding that changes only on re-upload, and
# the manifest cache-busts it with a ``?v=`` stamp, so this can be generous.
#
# ``private``, not ``public``: these responses vary per tenant while a shared
# CDN in front of many tenant hostnames may key its cache without the Host
# header — exactly the cross-tenant hazard ``ApiNoStoreCacheControlMiddleware``
# exists for. ``private`` keeps them in the browser cache (where the win is)
# and out of every shared one. That middleware allowlists these two paths so
# these headers survive; the two must stay in sync.
_APP_ICON_MAX_AGE = 60 * 60 * 24
# One hour: short enough that a rename or icon swap propagates the same day,
# long enough that the launcher isn't re-fetching it on every app open.
_MANIFEST_MAX_AGE = 60 * 60


def _tenant_from_schema() -> Tenant:
    """Resolve the tenant django-tenants routed this request to.

    Subdomain -> schema resolution already happened in ``TenantMainMiddleware``;
    this is only the lookup of the owning row.
    """
    schema_name = connection.schema_name

    if schema_name == "public":
        raise NoTenantContext("No tenant context")

    try:
        return Tenant.objects.get(schema_name=schema_name)
    except Tenant.DoesNotExist:
        raise NotFoundError("Tenant not found") from None


class CurrentTenantView(APIView):
    """Get current tenant information."""

    permission_classes = []  # Allow unauthenticated access for tenant detection
    # Anti-flood: this AllowAny bootstrap endpoint is otherwise unthrottled.
    # The global ScopedRateThrottle is a no-op until a scope is set; naming one
    # opts this view in (rate in settings DEFAULT_THROTTLE_RATES, keyed by IP).
    throttle_scope = "current_tenant"

    @extend_schema(
        tags=["tenants"],
        summary="Get current tenant",
        responses={
            200: CurrentTenantSerializer,
            400: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
    )
    def get(self, request: Request) -> Response:
        return Response(CurrentTenantSerializer(_tenant_from_schema()).data)


class TenantManifestView(APIView):
    """Serve the tenant's web app manifest (``display: standalone``).

    Rendered per request from the tenant row rather than shipped as a static
    file, because ONE built bundle is served to every tenant subdomain — a
    build-time manifest could only ever carry platform branding. The tenant is
    resolved from the subdomain exactly as every other request here is.

    Deliberately mounted under ``/api/tenants/`` and not at the origin root:
    the gateway sends everything outside ``/api/``, ``/health/``, ``/static/``
    and ``/media/`` to the frontend container, whose SPA fallback answers any
    unmatched path with ``index.html`` and HTTP 200 — a root-level manifest
    route would silently feed HTML to the manifest parser.

    This app's urlconf is not included by ``config.public_urls``, so the route
    404s on the super-admin/platform host. That is intentional and is what
    keeps the IP-allowlisted platform app from advertising itself as
    installable — no host-sniffing needed in the frontend.
    """

    permission_classes = []  # The browser fetches a manifest without credentials
    throttle_scope = "tenant_manifest"

    @extend_schema(exclude=True)  # Browser-fetched document, not a client API
    def get(self, request: Request) -> HttpResponseBase:
        tenant = _tenant_from_schema()

        # Same stamp the frontend gets in the tenant payload, so the manifest
        # and the runtime-injected apple-touch-icon never disagree about which
        # version of the icon they are pointing at.
        version = tenant.app_icon_version
        icon_src = (
            f"/api/tenants/app-icon.png?v={version}"
            if version
            else FALLBACK_APP_ICON_PATH
        )

        manifest = {
            # ``id`` pins app identity for the life of the install. Chrome
            # snapshots manifest metadata at install time and treats a changed
            # ``id`` / ``start_url`` as a DIFFERENT app rather than an update —
            # so neither may ever change once tenants have installed.
            "id": "/",
            "name": tenant.name,
            "short_name": tenant.app_short_name or tenant.name[:12],
            "start_url": "/",
            "scope": "/",
            "display": "standalone",
            "background_color": "#ffffff",
            "theme_color": "#ffffff",
            "icons": [
                {
                    "src": icon_src,
                    "sizes": "512x512",
                    "type": "image/png",
                    # ``any`` only — a ``maskable`` icon is cropped to the inner
                    # safe zone, which would eat the edges of an unpadded
                    # tenant logo. Declaring it would need a padded rendition.
                    "purpose": "any",
                }
            ],
        }

        response = JsonResponse(manifest, content_type="application/manifest+json")
        response.headers["Cache-Control"] = f"private, max-age={_MANIFEST_MAX_AGE}"
        return response


class TenantAppIconView(APIView):
    """Serve the tenant's launcher icon — unauthenticated and UNSIGNED.

    This deliberately bypasses the media capability gate. Every
    ``FileField.url`` on this platform is minted by
    ``SignedTenantFileSystemStorage`` with a ``?st=`` token that expires after
    ``MEDIA_URL_SIGNATURE_MAX_AGE`` (24h), and ``protected_media_view`` 403s
    without one — but a manifest icon is fetched by the browser/OS WITHOUT
    credentials and must keep resolving for the entire life of an installed
    app. A signed URL would leave every installed home screen showing a broken
    icon a day later.

    The exposure is one image that is public branding on a public-facing
    subdomain — the same category as ``tenant.name``, which
    ``CurrentTenantView`` already serves to anonymous callers. It is NOT the
    category of the invoice PDFs / e-invoice XML that share the internal
    ``/_protected_media/`` alias. Do not generalise this exemption, and do not
    weaken ``core.protected_media`` to whitelist image fields — that would
    relax the gate for every media file on the platform.
    """

    permission_classes = []  # Fetched by the launcher, which has no session
    throttle_scope = "tenant_app_icon"

    @extend_schema(exclude=True)  # Binary asset, not a client API
    def get(self, request: Request) -> HttpResponseBase:
        tenant = _tenant_from_schema()

        if not tenant.app_icon:
            raise NotFoundError("Tenant has no app icon")

        if settings.DEBUG:
            response: HttpResponseBase = FileResponse(
                tenant.app_icon.open("rb"), content_type="image/png"
            )
        else:
            # ``storage.url()`` is the only thing that knows the tenant-relative
            # media layout (``MULTITENANT_RELATIVE_MEDIA_ROOT``), so derive the
            # internal path from it rather than re-deriving the schema prefix
            # here. Strip the ``?st=`` token it appends — this endpoint is
            # deliberately the unsigned door.
            media_path = unquote(
                urlsplit(tenant.app_icon.url).path[len(settings.MEDIA_URL) :]
            )
            response = HttpResponse()
            # Drop Django's default ``text/html`` so nginx derives the type
            # from the file extension at the internal location.
            del response.headers["Content-Type"]
            response.headers["X-Accel-Redirect"] = quote(
                INTERNAL_MEDIA_LOCATION + media_path
            )

        response.headers["Cache-Control"] = f"private, max-age={_APP_ICON_MAX_AGE}"
        return response
