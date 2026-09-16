"""Tests for ``BackgroundJobViewSet.retrieve`` — the job-polling endpoint.

The frontend polls this with whatever id it was handed, so a malformed one is
ordinary traffic rather than an attack: it must answer 404, not 500 and not a
400 that a polling drawer would misread as "the job failed".
"""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.commissioning.tests.factories import JasminUserFactory
from apps.notifications.models import BackgroundJob


@pytest.fixture
def office_client(tenant):
    client = APIClient()
    client.force_authenticate(user=JasminUserFactory(roles=["office"]))
    return client


def _url(pk: str) -> str:
    return reverse("background-job-detail", kwargs={"pk": pk})


@pytest.mark.django_db
class TestBackgroundJobRetrieve:
    def test_returns_the_job(self, office_client, tenant):
        job = BackgroundJob.objects.create(kind="offer.bulk_send")

        resp = office_client.get(_url(str(job.id)))

        assert resp.status_code == 200
        assert resp.data["id"] == str(job.id)

    def test_unknown_id_is_404(self, office_client, tenant):
        resp = office_client.get(_url("2f1c8b1e-0000-4000-8000-000000000000"))

        assert resp.status_code == 404

    @pytest.mark.parametrize("bad_pk", ["not-a-uuid", "123", "abc-def"])
    def test_malformed_id_is_404(self, office_client, tenant, bad_pk):
        """``pk`` is a UUID column: an id that isn't one fails in the field's
        ``to_python`` with Django's ValidationError (not a ValueError), which
        the lookup has to catch to answer 404 rather than 400."""
        resp = office_client.get(_url(bad_pk))

        assert resp.status_code == 404
        assert resp.data["code"] == "not_found"
