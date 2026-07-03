"""The per-tenant default OfferGroup is seeded and protected from deletion."""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction
from django.urls import reverse
from rest_framework import status

from apps.commissioning.models import OfferGroup
from apps.commissioning.tests.factories import OfferGroupFactory

URL_LIST = reverse("offer_group-list")


def _detail_url(pk: str) -> str:
    return reverse("offer_group-detail", args=[pk])


@pytest.mark.django_db
class TestDefaultOfferGroup:
    def test_default_offer_group_is_seeded(self, tenant):
        # The data migration seeds exactly one default offer group per tenant.
        assert OfferGroup.objects.filter(is_default=True).count() == 1

    def test_default_cannot_be_deleted(self, api_client, tenant):
        default = OfferGroup.get_default()
        resp = api_client.delete(_detail_url(default.pk))
        assert resp.status_code == status.HTTP_409_CONFLICT
        assert resp.data["code"] == "offer_group.cannot_delete_default"
        assert OfferGroup.objects.filter(pk=default.pk).exists()

    def test_default_reports_not_deletable(self, api_client, tenant):
        # The list serializer marks the default as can_be_deleted=False so the
        # frontend hides its delete icon.
        resp = api_client.get(URL_LIST)
        assert resp.status_code == status.HTTP_200_OK
        default_row = next(r for r in resp.data if r["is_default"])
        assert default_row["can_be_deleted"] is False

    def test_non_default_can_be_deleted(self, api_client, tenant):
        og = OfferGroupFactory()  # is_default=False, no FK references
        resp = api_client.delete(_detail_url(og.pk))
        assert resp.status_code == status.HTTP_204_NO_CONTENT
        assert not OfferGroup.objects.filter(pk=og.pk).exists()

    def test_default_can_be_renamed_and_renumbered(self, api_client, tenant):
        # The office may freely edit the default group's name/number — only
        # deletion is blocked. is_default itself is read-only, so trying to
        # clear it via PATCH is ignored.
        default = OfferGroup.get_default()
        resp = api_client.patch(
            _detail_url(default.pk),
            {"name": "Haupt", "number": 7, "is_default": False},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        default.refresh_from_db()
        assert default.name == "Haupt"
        assert default.number == 7
        assert default.is_default is True

    def test_only_one_default_allowed(self, tenant):
        # The partial-unique constraint blocks a second default.
        with pytest.raises(IntegrityError), transaction.atomic():
            OfferGroupFactory(is_default=True)

    def test_seed_flags_lowest_numbered_existing_group(self, tenant):
        # Migration branch (b): for a tenant that already has offer groups but
        # no default (the path EVERY existing tenant takes on upgrade), the seed
        # must flag the lowest-NUMBERED group — not pick by insertion id, and
        # not create a duplicate "Standard".
        import importlib

        from django.apps import apps as django_apps

        seed = importlib.import_module(
            "apps.commissioning.migrations.0002_finalized_protection_and_reference_data"
        )._seed_default_offer_group

        OfferGroup.objects.all().delete()
        OfferGroupFactory(number=5)  # created first (lower id), higher number
        og3 = OfferGroupFactory(number=3)  # created second, lower number

        seed(django_apps, None)

        assert OfferGroup.objects.filter(is_default=True).count() == 1
        assert OfferGroup.get_default().pk == og3.pk  # lowest number, not id
        assert OfferGroup.objects.count() == 2  # no duplicate "Standard" row

        # Idempotent: a second run leaves the same single default untouched.
        seed(django_apps, None)
        assert OfferGroup.objects.filter(is_default=True).count() == 1
        assert OfferGroup.get_default().pk == og3.pk
