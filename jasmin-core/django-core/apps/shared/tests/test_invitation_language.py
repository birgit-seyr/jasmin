"""A provisioned user inherits only a SUPPORTED language from its tenant.

``Tenant.tenant_language`` is a free 8-character column; ``user_language`` is a
3-character column limited to ``LanguageChoices``. The invitation helper seeds
the user from the tenant, so it narrows the tenant value first — otherwise a
tenant set to an unshipped language seeds an out-of-enum code, and a regional
tag (``de-DE``) overflows the target column.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.shared.invitations import create_user_with_invitation

pytestmark = pytest.mark.django_db


@pytest.fixture()
def tenant_language(tenant):
    """Set ``tenant_language`` for one test and put the old value back."""
    original = tenant.tenant_language

    def _set(value: str) -> None:
        tenant.tenant_language = value
        tenant.save(update_fields=["tenant_language"])

    yield _set
    tenant.tenant_language = original
    tenant.save(update_fields=["tenant_language"])


def _invite(email: str):
    with patch("apps.shared.invitations._send_invitation_email"):
        user, _invitation = create_user_with_invitation(
            email=email,
            first_name="Nora",
            last_name="Newcomer",
        )
    user.refresh_from_db()
    return user


class TestTenantSeededUserLanguage:
    def test_a_supported_tenant_language_is_inherited(self, tenant_language):
        tenant_language("de")

        assert _invite("supported@example.com").user_language == "de"

    def test_an_unsupported_tenant_language_falls_back(self, tenant_language):
        # The tenant UI still offers fr/it although no templates ship for them.
        tenant_language("fr")

        assert _invite("unsupported@example.com").user_language == "en"

    def test_a_regional_tag_keeps_its_base_language(self, tenant_language):
        # "de-DE" would not even fit the 3-character user_language column.
        tenant_language("de-DE")

        assert _invite("regional@example.com").user_language == "de"

    def test_a_blank_tenant_language_falls_back(self, tenant_language):
        tenant_language("")

        assert _invite("blank@example.com").user_language == "en"

    def test_an_explicit_user_language_wins_over_the_tenant(self, tenant_language):
        tenant_language("de")

        with patch("apps.shared.invitations._send_invitation_email"):
            user, _invitation = create_user_with_invitation(
                email="explicit@example.com",
                first_name="Nora",
                last_name="Newcomer",
                user_language="en",
            )

        user.refresh_from_db()
        assert user.user_language == "en"
