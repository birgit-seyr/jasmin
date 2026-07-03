from django.conf import settings
from django.urls import include, path, re_path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

from apps.shared.csp_report import csp_report_view
from core.protected_media import protected_media_view

urlpatterns = [
    path("api/auth/", include("apps.accounts.urls")),
    path("api/commissioning/", include("apps.commissioning.urls")),
    path("api/cultivation/", include("apps.cultivation.urls")),
    path("api/staff/", include("apps.staff.urls")),
    path("api/economics/", include("apps.economics.urls")),
    path("api/payments/", include("apps.payments.urls")),
    path("api/tenants/", include("apps.shared.tenants.urls")),
    path("api/notifications/", include("apps.notifications.urls")),
    path("api/gdpr/", include("apps.gdpr.urls")),
    # Browsers POST CSP violation reports here (header set by nginx).
    path("api/csp-report/", csp_report_view, name="csp-report"),
    # Signed-URL media gate (replaces nginx serving /media/ directly
    # and the old DEBUG-only ``static()`` helper — same view handles
    # both: X-Accel-Redirect in prod, FileResponse under DEBUG).
    re_path(r"^media/(?P<path>.*)$", protected_media_view, name="protected-media"),
]

# API schema + interactive docs (Swagger / ReDoc). Dev-only: the schema is
# committed to react-core/schema.yml and regenerated in CI, so there's no
# need to serve the full API surface map to anonymous visitors in prod.
if settings.DEBUG:
    urlpatterns += [
        path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
        path(
            "api/docs/",
            SpectacularSwaggerView.as_view(url_name="schema"),
            name="swagger-ui",
        ),
        path(
            "api/redoc/",
            SpectacularRedocView.as_view(url_name="schema"),
            name="redoc",
        ),
    ]
