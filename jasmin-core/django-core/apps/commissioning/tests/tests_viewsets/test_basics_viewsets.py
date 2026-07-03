"""Tests for basics_viewsets.py — Season, Storage, ShareArticle CRUD and filtering."""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.urls import reverse
from rest_framework import status

from apps.commissioning.models import DefaultShareArticleInShare, Season
from apps.commissioning.tests.factories import (
    SeasonFactory,
    ShareArticleFactory,
    ShareArticleNetPriceFactory,
    ShareContentFactory,
    ShareTypeFactory,
    ShareTypeVariationFactory,
    StorageFactory,
)


# ---------------------------------------------------------------------------
# SeasonViewSet
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestSeasonViewSet:
    URL = reverse("season-list")

    def test_list_empty(self, api_client, tenant):
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data == []

    def test_list_returns_seasons(self, api_client, tenant):
        SeasonFactory()
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 1

    def test_create_season(self, api_client, tenant):
        resp = api_client.post(
            self.URL,
            {
                "valid_from": "2027-01-04",
                "valid_until": "2027-06-27",
                "weeks_without_delivery": [],
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED


@pytest.mark.django_db
class TestSeasonOneOpenConstraint:
    """SUC-9: a partial unique index backstops the global one-open invariant.
    handle_succession closes the predecessor on the normal save() path, so a
    duplicate OPEN season only arises through a bulk path that bypasses it."""

    def test_db_blocks_a_second_open_season(self, tenant):
        SeasonFactory(valid_from=datetime.date(2026, 1, 5), valid_until=None)
        # bulk_create bypasses save()/handle_succession → the DB index must
        # reject the second open (valid_until IS NULL) season.
        with pytest.raises(IntegrityError), transaction.atomic():
            Season.objects.bulk_create(
                [Season(valid_from=datetime.date(2027, 1, 4), valid_until=None)]
            )

    def test_db_allows_open_plus_closed_season(self, tenant):
        # A closed predecessor + one open successor is the normal shape and must
        # stay allowed (the index is partial on valid_until IS NULL).
        SeasonFactory(
            valid_from=datetime.date(2026, 1, 5),
            valid_until=datetime.date(2026, 12, 27),
        )
        SeasonFactory(valid_from=datetime.date(2027, 1, 4), valid_until=None)
        assert Season.objects.filter(valid_until__isnull=True).count() == 1


# ---------------------------------------------------------------------------
# StorageViewSet
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestStorageViewSet:
    URL = reverse("storages-list")

    @pytest.fixture(autouse=True)
    def _clear_seeded_storages(self, tenant):
        # commissioning/migrations/0004 seeds "Kurz" + "Lang" into every
        # tenant schema. These tests assert exact counts, so wipe the
        # seed before each case (rolled back with the test transaction).
        from apps.commissioning.models import Storage

        Storage.objects.all().delete()

    def test_list_empty(self, api_client, tenant):
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data == []

    def test_list_returns_storages(self, api_client, tenant):
        StorageFactory(is_active=True)
        resp = api_client.get(self.URL)
        assert len(resp.data) == 1

    def test_filter_is_active_true(self, api_client, tenant):
        StorageFactory(is_active=True, name="Active")
        StorageFactory(is_active=False, name="Inactive")
        resp = api_client.get(self.URL, {"is_active": "true"})
        assert len(resp.data) == 1
        assert resp.data[0]["name"] == "Active"

    def test_filter_is_active_false(self, api_client, tenant):
        StorageFactory(is_active=True, name="Active")
        StorageFactory(is_active=False, name="Inactive")
        resp = api_client.get(self.URL, {"is_active": "false"})
        assert len(resp.data) == 1
        assert resp.data[0]["name"] == "Inactive"

    def test_ordered_by_name(self, api_client, tenant):
        StorageFactory(name="Zeta")
        StorageFactory(name="Alpha")
        resp = api_client.get(self.URL)
        names = [s["name"] for s in resp.data]
        assert names == sorted(names)


# ---------------------------------------------------------------------------
# ShareArticleViewSet
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestShareArticleViewSet:
    URL = reverse("share_article-list")

    def test_list_empty(self, api_client, tenant):
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK

    def test_list_returns_articles(self, api_client, tenant):
        ShareArticleFactory()
        resp = api_client.get(self.URL)
        assert len(resp.data) >= 1

    def test_filter_is_active(self, api_client, tenant):
        ShareArticleFactory(is_active=True)
        ShareArticleFactory(is_active=False)
        resp = api_client.get(self.URL, {"is_active": "true"})
        for item in resp.data:
            assert item["is_active"] is True

    def test_retrieve_returns_article(self, api_client, tenant):
        article = ShareArticleFactory(name="Carrots")
        url = reverse("share_article-detail", kwargs={"pk": article.pk})
        resp = api_client.get(url)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["name"] == "Carrots"

    def test_partial_update_changes_name(self, api_client, tenant):
        """ShareArticleViewSet has a custom ``update`` method that splits
        share_option_list assignment off — the field-set update path needs
        a happy-path test."""
        article = ShareArticleFactory(name="OldName")
        url = reverse("share_article-detail", kwargs={"pk": article.pk})
        resp = api_client.patch(url, {"name": "NewName"}, format="json")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["name"] == "NewName"
        article.refresh_from_db()
        assert article.name == "NewName"

    def test_create_article(self, api_client, tenant):
        """Custom ``create`` writes the row + reads it back through the
        get_queryset-annotated form — exercises the round-trip."""
        resp = api_client.post(
            self.URL,
            {
                "name": "Beets",
                "default_movement_unit": "KG",
                "is_active": True,
                "share_option": "HARVEST_SHARE",
                "share_option_list": ["HARVEST_SHARE"],
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data["name"] == "Beets"

    def test_delete_article(self, api_client, tenant):
        article = ShareArticleFactory()
        url = reverse("share_article-detail", kwargs={"pk": article.pk})
        resp = api_client.delete(url)
        assert resp.status_code == status.HTTP_204_NO_CONTENT
        from apps.commissioning.models import ShareArticle

        assert not ShareArticle.objects.filter(pk=article.pk).exists()


# ---------------------------------------------------------------------------
# StorageViewSet — edit/delete CRUD
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestStorageViewSetEditDelete:
    def test_retrieve(self, api_client, tenant):
        storage = StorageFactory(name="Cold Room A")
        url = reverse("storages-detail", kwargs={"pk": storage.pk})
        resp = api_client.get(url)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["name"] == "Cold Room A"

    def test_partial_update(self, api_client, tenant):
        storage = StorageFactory(name="Initial")
        url = reverse("storages-detail", kwargs={"pk": storage.pk})
        resp = api_client.patch(url, {"name": "Renamed"}, format="json")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["name"] == "Renamed"

    def test_delete(self, api_client, tenant):
        from apps.commissioning.models import Storage

        storage = StorageFactory()
        url = reverse("storages-detail", kwargs={"pk": storage.pk})
        resp = api_client.delete(url)
        assert resp.status_code == status.HTTP_204_NO_CONTENT
        assert not Storage.objects.filter(pk=storage.pk).exists()


# ---------------------------------------------------------------------------
# CrateViewSet — list / edit / delete CRUD
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCrateViewSet:
    URL = reverse("crates-list")

    def test_list_empty(self, api_client, tenant):
        from apps.commissioning.models import Crate

        Crate.objects.all().delete()
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data == []

    def test_list_returns_crates(self, api_client, tenant):
        from apps.commissioning.tests.factories import CrateFactory

        CrateFactory(name="EuroBox")
        resp = api_client.get(self.URL)
        names = [c["name"] for c in resp.data]
        assert "EuroBox" in names

    def test_partial_update(self, api_client, tenant):
        from apps.commissioning.tests.factories import CrateFactory

        crate = CrateFactory(name="OldCrate")
        url = reverse("crates-detail", kwargs={"pk": crate.pk})
        resp = api_client.patch(url, {"name": "NewCrate"}, format="json")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["name"] == "NewCrate"

    def test_delete(self, api_client, tenant):
        from apps.commissioning.models import Crate
        from apps.commissioning.tests.factories import CrateFactory

        crate = CrateFactory()
        url = reverse("crates-detail", kwargs={"pk": crate.pk})
        resp = api_client.delete(url)
        assert resp.status_code == status.HTTP_204_NO_CONTENT
        assert not Crate.objects.filter(pk=crate.pk).exists()


# ---------------------------------------------------------------------------
# DefaultShareArticleInShareViewSet
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestDefaultShareArticleInShareViewSet:
    URL = reverse("default_share_articles_in_share-list")
    BULK_URL = reverse("default_share_articles_in_share-bulk-upsert")

    # ---- list / filter ---------------------------------------------------
    def test_list_empty(self, api_client, tenant):
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data == []

    def test_list_returns_rows(self, api_client, tenant):
        DefaultShareArticleInShare.objects.create(
            share_article=ShareArticleFactory(),
            share_type_variation=ShareTypeVariationFactory(),
            quantity=Decimal("1.500"),
            unit="KG",
        )
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 1
        row = resp.data[0]
        # read-only annotations from the serializer
        assert "share_article_name" in row
        assert "share_type_variation_size" in row
        assert "share_type_id" in row

    def test_filter_by_share_article(self, api_client, tenant):
        wanted_article = ShareArticleFactory()
        other_article = ShareArticleFactory()
        DefaultShareArticleInShare.objects.create(
            share_article=wanted_article,
            share_type_variation=ShareTypeVariationFactory(),
            quantity=Decimal("1.000"),
            unit="KG",
        )
        DefaultShareArticleInShare.objects.create(
            share_article=other_article,
            share_type_variation=ShareTypeVariationFactory(),
            quantity=Decimal("2.000"),
            unit="KG",
        )
        resp = api_client.get(self.URL, {"share_article": wanted_article.pk})
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 1
        assert resp.data[0]["share_article"] == wanted_article.pk

    def test_filter_by_share_type_variation(self, api_client, tenant):
        wanted_variation = ShareTypeVariationFactory()
        other_variation = ShareTypeVariationFactory()
        article = ShareArticleFactory()
        DefaultShareArticleInShare.objects.create(
            share_article=article,
            share_type_variation=wanted_variation,
            quantity=Decimal("1.000"),
            unit="KG",
        )
        DefaultShareArticleInShare.objects.create(
            share_article=ShareArticleFactory(),
            share_type_variation=other_variation,
            quantity=Decimal("2.000"),
            unit="KG",
        )
        resp = api_client.get(self.URL, {"share_type_variation": wanted_variation.pk})
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 1
        assert resp.data[0]["share_type_variation"] == wanted_variation.pk

    def test_filter_by_share_type(self, api_client, tenant):
        wanted_type = ShareTypeFactory()
        other_type = ShareTypeFactory(share_option="CHICKEN_SHARE")
        wanted_variation = ShareTypeVariationFactory(share_type=wanted_type)
        other_variation = ShareTypeVariationFactory(share_type=other_type)
        DefaultShareArticleInShare.objects.create(
            share_article=ShareArticleFactory(),
            share_type_variation=wanted_variation,
            quantity=Decimal("1.000"),
            unit="KG",
        )
        DefaultShareArticleInShare.objects.create(
            share_article=ShareArticleFactory(),
            share_type_variation=other_variation,
            quantity=Decimal("2.000"),
            unit="KG",
        )
        resp = api_client.get(self.URL, {"share_type": wanted_type.pk})
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 1
        assert resp.data[0]["share_type_id"] == wanted_type.pk

    # ---- CRUD -----------------------------------------------------------
    def test_create(self, api_client, tenant):
        article = ShareArticleFactory()
        variation = ShareTypeVariationFactory()
        resp = api_client.post(
            self.URL,
            {
                "share_article": article.pk,
                "share_type_variation": variation.pk,
                "quantity": "2.500",
                "unit": "KG",
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        assert DefaultShareArticleInShare.objects.count() == 1
        row = DefaultShareArticleInShare.objects.first()
        assert row.share_article_id == article.pk
        assert row.share_type_variation_id == variation.pk
        assert row.quantity == Decimal("2.500")
        assert row.unit == "KG"

    def test_update(self, api_client, tenant):
        row = DefaultShareArticleInShare.objects.create(
            share_article=ShareArticleFactory(),
            share_type_variation=ShareTypeVariationFactory(),
            quantity=Decimal("1.000"),
            unit="KG",
        )
        url = reverse("default_share_articles_in_share-detail", kwargs={"pk": row.pk})
        resp = api_client.patch(url, {"quantity": "9.999"}, format="json")
        assert resp.status_code == status.HTTP_200_OK
        row.refresh_from_db()
        assert row.quantity == Decimal("9.999")

    def test_delete(self, api_client, tenant):
        row = DefaultShareArticleInShare.objects.create(
            share_article=ShareArticleFactory(),
            share_type_variation=ShareTypeVariationFactory(),
            quantity=Decimal("1.000"),
            unit="KG",
        )
        url = reverse("default_share_articles_in_share-detail", kwargs={"pk": row.pk})
        resp = api_client.delete(url)
        assert resp.status_code == status.HTTP_204_NO_CONTENT
        assert not DefaultShareArticleInShare.objects.filter(pk=row.pk).exists()

    # ---- bulk_upsert ----------------------------------------------------
    def test_bulk_upsert_creates_new_entries(self, api_client, tenant):
        article = ShareArticleFactory(default_movement_unit="KG")
        v1 = ShareTypeVariationFactory()
        v2 = ShareTypeVariationFactory()
        resp = api_client.post(
            self.BULK_URL,
            {
                "share_article": article.pk,
                "entries": [
                    {"share_type_variation": v1.pk, "quantity": "1.500"},
                    {"share_type_variation": v2.pk, "quantity": "0.250"},
                ],
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert (
            DefaultShareArticleInShare.objects.filter(share_article=article).count()
            == 2
        )
        assert len(resp.data) == 2

    def test_bulk_upsert_updates_existing(self, api_client, tenant):
        article = ShareArticleFactory(default_movement_unit="KG")
        variation = ShareTypeVariationFactory()
        DefaultShareArticleInShare.objects.create(
            share_article=article,
            share_type_variation=variation,
            quantity=Decimal("1.000"),
            unit="KG",
        )
        resp = api_client.post(
            self.BULK_URL,
            {
                "share_article": article.pk,
                "entries": [
                    {"share_type_variation": variation.pk, "quantity": "5.000"},
                ],
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        rows = DefaultShareArticleInShare.objects.filter(share_article=article)
        assert rows.count() == 1
        assert rows.first().quantity == Decimal("5.000")

    def test_bulk_upsert_deletes_when_quantity_null(self, api_client, tenant):
        article = ShareArticleFactory(default_movement_unit="KG")
        variation = ShareTypeVariationFactory()
        DefaultShareArticleInShare.objects.create(
            share_article=article,
            share_type_variation=variation,
            quantity=Decimal("1.000"),
            unit="KG",
        )
        resp = api_client.post(
            self.BULK_URL,
            {
                "share_article": article.pk,
                "entries": [
                    {"share_type_variation": variation.pk, "quantity": None},
                ],
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert not DefaultShareArticleInShare.objects.filter(
            share_article=article
        ).exists()

    def test_bulk_upsert_deletes_when_quantity_zero(self, api_client, tenant):
        article = ShareArticleFactory(default_movement_unit="KG")
        variation = ShareTypeVariationFactory()
        DefaultShareArticleInShare.objects.create(
            share_article=article,
            share_type_variation=variation,
            quantity=Decimal("1.000"),
            unit="KG",
        )
        resp = api_client.post(
            self.BULK_URL,
            {
                "share_article": article.pk,
                "entries": [
                    {"share_type_variation": variation.pk, "quantity": "0"},
                ],
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert not DefaultShareArticleInShare.objects.filter(
            share_article=article
        ).exists()

    def test_bulk_upsert_falls_back_to_share_article_default_unit(
        self, api_client, tenant
    ):
        article = ShareArticleFactory(default_movement_unit="KG")
        variation = ShareTypeVariationFactory()
        resp = api_client.post(
            self.BULK_URL,
            {
                "share_article": article.pk,
                "entries": [
                    {"share_type_variation": variation.pk, "quantity": "1.000"},
                ],
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        row = DefaultShareArticleInShare.objects.get(share_article=article)
        assert row.unit == "KG"

    def test_bulk_upsert_uses_explicit_unit(self, api_client, tenant):
        article = ShareArticleFactory(default_movement_unit="KG")
        variation = ShareTypeVariationFactory()
        resp = api_client.post(
            self.BULK_URL,
            {
                "share_article": article.pk,
                "entries": [
                    {
                        "share_type_variation": variation.pk,
                        "quantity": "1.000",
                        "unit": "PIECE",
                    },
                ],
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        row = DefaultShareArticleInShare.objects.get(share_article=article)
        assert row.unit == "PIECE"

    def test_bulk_upsert_returns_only_rows_for_share_article(self, api_client, tenant):
        article = ShareArticleFactory(default_movement_unit="KG")
        other_article = ShareArticleFactory(default_movement_unit="KG")
        variation = ShareTypeVariationFactory()
        # pre-existing row for a different article should not appear
        DefaultShareArticleInShare.objects.create(
            share_article=other_article,
            share_type_variation=variation,
            quantity=Decimal("3.000"),
            unit="KG",
        )
        resp = api_client.post(
            self.BULK_URL,
            {
                "share_article": article.pk,
                "entries": [
                    {"share_type_variation": variation.pk, "quantity": "1.000"},
                ],
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 1
        assert resp.data[0]["share_article"] == article.pk

    def test_bulk_upsert_share_article_not_found_returns_404(self, api_client, tenant):
        resp = api_client.post(
            self.BULK_URL,
            {
                "share_article": "does-not-exist",
                "entries": [],
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_bulk_upsert_validation_error_for_missing_entries(self, api_client, tenant):
        article = ShareArticleFactory()
        resp = api_client.post(
            self.BULK_URL,
            {"share_article": article.pk},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    # ---- permissions ----------------------------------------------------
    def test_member_user_cannot_write(self, anon_client, member_user, tenant):
        anon_client.force_authenticate(user=member_user)
        resp = anon_client.post(
            self.URL,
            {
                "share_article": ShareArticleFactory().pk,
                "share_type_variation": ShareTypeVariationFactory().pk,
                "quantity": "1.000",
                "unit": "KG",
            },
            format="json",
        )
        assert resp.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )
        assert DefaultShareArticleInShare.objects.count() == 0

    def test_anonymous_cannot_list(self, anon_client, tenant):
        resp = anon_client.get(self.URL)
        assert resp.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )


# ---------------------------------------------------------------------------
# ShareArticleNetPriceViewSet — deletability
# ---------------------------------------------------------------------------
URL_SHARE_ARTICLE_NET_PRICE = reverse("share_article_net_price-list")


@pytest.mark.django_db
class TestShareArticleNetPriceViewSet:
    def _can_delete(self, api_client, price_id) -> bool:
        resp = api_client.get(URL_SHARE_ARTICLE_NET_PRICE)
        return next(r for r in resp.data if r["id"] == str(price_id))["can_be_deleted"]

    def test_active_price_not_deletable_when_article_in_use(self, api_client, tenant):
        # An ACTIVE price becomes non-deletable once the article is in use — here
        # via a member-share ShareContent, a HIDDEN ``related_name="+"`` relation
        # that ``can_delete_instance`` misses but ``parent_in_use`` catches.
        price = ShareArticleNetPriceFactory()  # active 2026-01-05..2026-12-27
        assert self._can_delete(api_client, price.id) is True
        ShareContentFactory(share_article=price.share_article)
        assert self._can_delete(api_client, price.id) is False

    def test_future_price_deletable_even_when_article_in_use(self, api_client, tenant):
        # Future (and past) prices stay deletable regardless of usage.
        article = ShareArticleFactory()
        ShareContentFactory(share_article=article)
        future = ShareArticleNetPriceFactory(
            share_article=article,
            valid_from=datetime.date(2027, 1, 4),  # Monday, future
            valid_until=None,
        )
        assert self._can_delete(api_client, future.id) is True
