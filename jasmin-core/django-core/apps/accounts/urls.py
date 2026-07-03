from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views
from .viewsets import AdminUserViewSet

router = DefaultRouter()
router.register("admin/users", AdminUserViewSet, basename="admin-users")

urlpatterns = [
    path("login/", views.user_login_view, name="login"),
    path("logout/", views.user_logout_view, name="logout"),
    path("logout-all/", views.user_logout_all_view, name="logout_all"),
    path("refresh/", views.user_token_refresh_view, name="refresh_token"),
    # Public self-registration (Scenario 2: user signs up + applies for member)
    path("register/", views.public_register_view, name="register"),
    # Invitation flow (Scenario 1: staff/admin invites user)
    path(
        "invitations/<uuid:token>/",
        views.invitation_verify_view,
        name="invitation_verify",
    ),
    path(
        "invitations/accept/",
        views.invitation_accept_view,
        name="invitation_accept",
    ),
    # Password reset (forgot-password flow)
    path(
        "password-reset/request/",
        views.password_reset_request_view,
        name="password_reset_request",
    ),
    path(
        "password-reset/confirm/",
        views.password_reset_confirm_view,
        name="password_reset_confirm",
    ),
    # Step-up authentication. Re-validates the caller's password
    # (and TOTP code, when ``STEP_UP_REQUIRES_TOTP`` is on) and
    # returns a new access token carrying ``step_up_verified_at``.
    # The frontend interceptor swaps the token in and retries the
    # original destructive request.
    path("step-up/", views.step_up_view, name="step_up"),
    # Two-factor auth (TOTP). See apps/accounts/views/two_factor_views.py.
    # URL segment is ``two-factor/`` (not ``2fa/``) for two reasons:
    # consistency with this app's kebab-case style (``password-reset/``,
    # ``admin/users/``) AND so orval generates clean JS identifiers
    # from the OpenAPI spec — segments starting with a digit force an
    # explicit ``operation_id`` everywhere.
    path(
        "two-factor/status/",
        views.two_factor_status_view,
        name="two_factor_status",
    ),
    path(
        "two-factor/enroll-start/",
        views.two_factor_enroll_start_view,
        name="two_factor_enroll_start",
    ),
    path(
        "two-factor/enroll-confirm/",
        views.two_factor_enroll_confirm_view,
        name="two_factor_enroll_confirm",
    ),
    path(
        "two-factor/verify/",
        views.two_factor_verify_view,
        name="two_factor_verify",
    ),
    path(
        "two-factor/disable/",
        views.two_factor_disable_view,
        name="two_factor_disable",
    ),
    path(
        "two-factor/recovery-codes/regenerate/",
        views.two_factor_regenerate_recovery_codes_view,
        name="two_factor_regenerate_recovery_codes",
    ),
    # Admin user management — handled by AdminUserViewSet under /admin/users/.
    # Routes produced by the router:
    #   GET    /admin/users/
    #   POST   /admin/users/
    #   PATCH  /admin/users/<pk>/
    #   POST   /admin/users/<pk>/resend-invitation/
    path("", include(router.urls)),
    # Catch-all: must come AFTER the router include so /admin/users/* matches
    # the viewset, not this single-segment fallback.
    path("<str:user_id>/", views.user_profile_update_view, name="user_profile_update"),
]
