from django.conf import settings
from django.http import JsonResponse
from django.urls import include, path, re_path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

from apps.shared.csp_report import csp_report_view
from core.protected_media import protected_media_view


def debug_schema(request):
    tenant_info = {
        "host": request.get_host(),
        "has_tenant_attr": hasattr(request, "tenant"),
    }

    if hasattr(request, "tenant"):
        tenant_info.update(
            {
                "tenant_schema": request.tenant.schema_name,
                "tenant_name": getattr(request.tenant, "name", "No name"),
                "is_public_schema": request.tenant.schema_name == "public",
            }
        )

    return JsonResponse(tenant_info)


urlpatterns = [
    # CSP violation reports (browsers POST here when a CSP directive fails).
    path("api/csp-report/", csp_report_view, name="csp-report"),
    # Super admin endpoints. Single mount on purpose: a second mount of
    # the same include (the old ``api/management/``) duplicated every
    # operation in the public schema with colliding operationIds, and
    # made ``reverse()`` ambiguous (same ``app_name``, no instance
    # namespaces). Nothing ever called the alias.
    path("api/super-admin/", include("apps.shared.super_admin.urls")),
    # Super-admin support tickets. Second include under the same prefix (Django
    # falls through to it for /api/super-admin/support-tickets/…); kept in the
    # support app for cohesion. Inherits the /api/super-admin/ IP allowlist.
    path("api/super-admin/", include("apps.shared.support.admin_urls")),
    # Signed-URL media gate for public-schema uploads, if any. NOTE:
    # this route cannot serve TENANT media — the view binds the path's
    # schema prefix to ``connection.schema_name`` ("public" here), so
    # any ``media/<tenant_schema>/...`` request 403s. If super-admin
    # pages ever need to render tenant logos, add an explicit
    # public-schema exemption in ``core/protected_media.py`` (a valid
    # signature already proves the backend minted the URL).
    re_path(r"^media/(?P<path>.*)$", protected_media_view, name="protected-media"),
]

if settings.DEBUG:
    # Tenant-resolution debug endpoint. Dev-only: it discloses schema
    # names and tenant metadata to unauthenticated callers, so it must
    # never be registered in production.
    urlpatterns.append(path("debug/", debug_schema))
    # API schema + interactive docs (Swagger / ReDoc). Dev-only for the
    # same reason: the committed react-core/schema.yml (regenerated in CI)
    # is the source of truth, so the full API surface map isn't served to
    # anonymous visitors in production.
    urlpatterns += [
        path(
            "api/schema/",
            SpectacularAPIView.as_view(urlconf="config.public_urls"),
            name="public-schema",
        ),
        path(
            "api/docs/",
            SpectacularSwaggerView.as_view(url_name="public-schema"),
            name="public-swagger-ui",
        ),
        path(
            "api/redoc/",
            SpectacularRedocView.as_view(url_name="public-schema"),
            name="public-redoc",
        ),
    ]
