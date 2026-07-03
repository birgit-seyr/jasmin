"""Accounts view package.

Re-exports every view function so ``from apps.accounts import views`` /
``from . import views`` keeps resolving them by name (``views.user_login_view``,
``views.two_factor_status_view``), regardless of which module they live in.
``auth_views`` = login / register / invitation / password-reset / step-up;
``two_factor_views`` = the TOTP enrol → verify → disable flow.
"""

from .auth_views import (
    invitation_accept_view,
    invitation_verify_view,
    password_reset_confirm_view,
    password_reset_request_view,
    public_register_view,
    step_up_view,
    user_login_view,
    user_logout_all_view,
    user_logout_view,
    user_profile_update_view,
    user_token_refresh_view,
)
from .two_factor_views import (
    two_factor_disable_view,
    two_factor_enroll_confirm_view,
    two_factor_enroll_start_view,
    two_factor_regenerate_recovery_codes_view,
    two_factor_status_view,
    two_factor_verify_view,
)

__all__ = [
    "invitation_accept_view",
    "invitation_verify_view",
    "password_reset_confirm_view",
    "password_reset_request_view",
    "public_register_view",
    "step_up_view",
    "user_login_view",
    "user_logout_all_view",
    "user_logout_view",
    "user_profile_update_view",
    "user_token_refresh_view",
    "two_factor_disable_view",
    "two_factor_enroll_confirm_view",
    "two_factor_enroll_start_view",
    "two_factor_regenerate_recovery_codes_view",
    "two_factor_status_view",
    "two_factor_verify_view",
]
