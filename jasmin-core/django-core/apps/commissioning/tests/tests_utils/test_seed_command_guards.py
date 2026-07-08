"""The credential-writing seed commands must refuse to run outside DEBUG.

They mint fixed-password logins (``seed_test_users`` even an ADMIN), so an
accidental invocation against a production schema — the exact thing the guarded
wrapper commands protect against — must fail loudly rather than plant a
known-credential account.
"""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings


@pytest.mark.django_db
@pytest.mark.parametrize(
    "command, kwargs",
    [
        ("seed_test_users", {}),
    ],
)
def test_credential_seed_commands_refuse_without_debug(command, kwargs, tenant):
    with override_settings(DEBUG=False):
        with pytest.raises(CommandError, match="DEBUG=False"):
            call_command(command, **kwargs)
