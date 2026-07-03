from django.apps import AppConfig


class AuthzConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.authz"
    verbose_name = "Authorization"

    def ready(self) -> None:
        # Side-effect import: registers the drf-spectacular auth scheme
        # for TenantBoundJWTAuthentication (silences ~70 "could not
        # resolve authenticator" warnings at schema generation).
        from . import openapi  # noqa: F401
