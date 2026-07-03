import logging

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db import connection
from django.db.models import Q

logger = logging.getLogger(__name__)


class EmailOrUsernameModelBackend(ModelBackend):
    """
    Authenticate using either username or email for JasminUser
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        logger.debug("auth.lookup schema=%s", connection.schema_name)

        # Skip if we're in public schema (that's for SuperAdmin)
        if connection.schema_name == "public":
            logger.debug("auth.skip reason=public_schema")
            return None

        # Get the input (could be email or username)
        login_input = username or kwargs.get("email")

        if login_input is None or password is None:
            return None

        UserModel = get_user_model()

        try:
            # Since USERNAME_FIELD = "email", try both email and username fields
            user = UserModel.objects.get(
                Q(email__iexact=login_input) | Q(username__iexact=login_input)
            )
        except UserModel.DoesNotExist:
            logger.debug("auth.user_not_found")
            # Run password hasher to prevent timing attacks
            UserModel().set_password(password)
            return None
        except UserModel.MultipleObjectsReturned:
            logger.error(
                "auth.multiple_users_for_login schema=%s", connection.schema_name
            )
            return None

        # Check password only. Account status (pending/inactive) is enforced
        # by the auth_service so it can return a precise, user-facing reason
        # instead of a generic "Invalid credentials" error.
        if user.check_password(password):
            return user
        return None
