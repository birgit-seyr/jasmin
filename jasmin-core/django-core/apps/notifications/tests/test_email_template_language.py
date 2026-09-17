"""``?language=`` on the email-template endpoints.

These endpoints read, write and delete the override row for the language they
resolve, so a value that cannot be mapped is refused rather than falling back
to the tenant default — otherwise a typo would edit or drop the tenant's own
template. The spellings ``normalize_language`` does accept keep resolving.
"""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.commissioning.tests.factories import JasminUserFactory
from apps.notifications.models import EmailTemplate

SLUG = "accounts.invitation"
DETAIL_URL = reverse("email-template-detail", kwargs={"slug": SLUG})
RESET_URL = reverse("email-template-reset", kwargs={"slug": SLUG})


@pytest.fixture()
def admin_client(tenant):
    client = APIClient()
    client.force_authenticate(user=JasminUserFactory(roles=["admin"]))
    return client


@pytest.mark.django_db
class TestUnmappableLanguageIsRefused:
    def test_retrieve_refuses_unknown_language(self, admin_client, tenant):
        resp = admin_client.get(DETAIL_URL, {"language": "xx"})

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "email_template.unsupported_language"
        assert resp.data["field"] == "language"

    def test_update_writes_no_override(self, admin_client, tenant):
        resp = admin_client.patch(
            f"{DETAIL_URL}?language=xx", {"subject": "Neuer Betreff"}, format="json"
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "email_template.unsupported_language"
        # The row the fallback language would have received must not exist.
        assert not EmailTemplate.objects.filter(slug=SLUG).exists()

    def test_reset_deletes_no_override(self, admin_client, tenant):
        for language in ("de", "en"):
            EmailTemplate.objects.create(
                slug=SLUG, language=language, subject="Custom", is_customized=True
            )

        resp = admin_client.post(f"{RESET_URL}?language=xx")

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "email_template.unsupported_language"
        assert EmailTemplate.objects.filter(slug=SLUG).count() == 2


@pytest.mark.django_db
class TestAcceptedLanguagesStillResolve:
    @pytest.mark.parametrize(
        "value", ["de", "DE", "de-DE", "de_DE", "deutsch", "german"]
    )
    def test_accepted_spelling_resolves(self, admin_client, tenant, value):
        resp = admin_client.get(DETAIL_URL, {"language": value})

        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert resp.data["language"] == "de"

    @pytest.mark.parametrize("params", [{}, {"language": ""}, {"language": "  "}])
    def test_absent_or_blank_language_falls_back(self, admin_client, tenant, params):
        """Only a value that was actually sent is judged — no parameter means
        the tenant default, exactly as before."""
        resp = admin_client.get(DETAIL_URL, params)

        assert resp.status_code == status.HTTP_200_OK, resp.data
