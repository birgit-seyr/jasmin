"""Tests for finalize_views.py — BulkFinalize/Unfinalize views."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status

from apps.commissioning.models import ShareContent
from apps.commissioning.tests.factories import (
    DeliveryNoteContentFactory,
    JasminUserFactory,
    OrderFactory,
    ResellerFactory,
    ShareArticleFactory,
    ShareContentFactory,
    ShareFactory,
    ShareTypeVariationFactory,
)
from apps.commissioning.views.finalize_views import _get_finalization_status

URL_FINALIZE = reverse("bulk_finalize")
URL_UNFINALIZE = reverse("bulk_unfinalize")
URL_FINALIZE_SC = reverse("bulk_finalize_share_content")
URL_UNFINALIZE_SC = reverse("bulk_unfinalize_share_content")


def _finalizable_invoice(tenant):
    """An InvoiceReseller with one item, not yet finalized — ready for the
    bulk endpoint to finalize. Mirrors the setup in test_invoice_service."""
    from apps.commissioning.models import DeliveryNoteReseller
    from apps.commissioning.services import InvoiceService

    user = JasminUserFactory()
    reseller = ResellerFactory()
    order = OrderFactory(reseller=reseller)
    delivery_note = DeliveryNoteReseller.objects.create(order=order, date=date.today())
    DeliveryNoteContentFactory(
        delivery_note=delivery_note,
        share_article=ShareArticleFactory(),
        amount=Decimal("10.000"),
        unit="KG",
        size="M",
        price_per_unit=Decimal("2.50"),
    )
    delivery_note.finalize(user=user)
    return InvoiceService.create_from_delivery_note(delivery_note)


# ---------------------------------------------------------------------------
# BulkFinalizeView
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestBulkFinalizeView:
    def test_finalizes_orders(self, api_client, tenant):
        o1 = OrderFactory()
        o2 = OrderFactory()

        resp = api_client.post(
            URL_FINALIZE,
            {"model": "Order", "ids": [str(o1.id), str(o2.id)]},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["finalized_count"] == 2

    def test_already_finalized(self, api_client, tenant):
        o = OrderFactory()
        # Finalize via queryset to avoid FinalizedProtectedMixin issues
        type(o).objects.filter(pk=o.pk).update(is_finalized=True)
        o.refresh_from_db()

        resp = api_client.post(
            URL_FINALIZE,
            {"model": "Order", "ids": [str(o.id)]},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["already_finalized_count"] == 1

    def test_missing_model_returns_400(self, api_client, tenant):
        resp = api_client.post(
            URL_FINALIZE,
            {"ids": ["some-id"]},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_missing_ids_returns_400(self, api_client, tenant):
        resp = api_client.post(
            URL_FINALIZE,
            {"model": "Order"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_empty_ids_returns_400(self, api_client, tenant):
        resp = api_client.post(
            URL_FINALIZE,
            {"model": "Order", "ids": []},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_nonexistent_ids_returns_404(self, api_client, tenant):
        resp = api_client.post(
            URL_FINALIZE,
            {"model": "Order", "ids": ["00000000-0000-0000-0000-000000000000"]},
            format="json",
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_invalid_model_returns_400(self, api_client, tenant):
        resp = api_client.post(
            URL_FINALIZE,
            {"model": "NonExistentModel", "ids": ["x"]},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_mixed_batch_one_empty_invoice_does_not_roll_back_the_valid_one(
        self, api_client, tenant
    ):
        """A single bad item (an empty, item-less invoice raising a
        commissioning ``JasminError``) must NOT abort the whole batch: the
        valid invoice still finalizes and the empty one is reported in
        ``errors[]``. Before the fix the domain error escaped the per-item
        loop, propagated out of the view's ``@transaction.atomic`` and rolled
        back every already-finalized item, breaking the partial-success
        contract. A partial failure now also surfaces as HTTP 207."""
        from apps.commissioning.models import InvoiceReseller

        valid = _finalizable_invoice(tenant)
        empty = InvoiceReseller.objects.create(
            reseller=ResellerFactory(), date=date.today()
        )

        resp = api_client.post(
            URL_FINALIZE,
            {
                "model": "InvoiceReseller",
                "ids": [str(valid.id), str(empty.id)],
            },
            format="json",
        )

        # Partial success → 207 Multi-Status (not 200), so a client branching
        # on the status line sees the failure instead of skipping errors[].
        assert resp.status_code == status.HTTP_207_MULTI_STATUS
        assert resp.data["finalized_count"] == 1
        assert len(resp.data["errors"]) == 1
        assert resp.data["errors"][0]["id"] == str(empty.id)

        # Non-vacuity / the actual regression guard: the valid invoice really
        # persisted as finalized (the empty one's failure did not roll back the
        # outer atomic block), and the empty one stayed unfinalized.
        valid.refresh_from_db()
        assert valid.is_finalized is True
        empty.refresh_from_db()
        assert empty.is_finalized is False

    def test_all_succeed_returns_200_with_no_errors(self, api_client, tenant):
        """The lower boundary of the 207 contract: a fully-successful batch
        stays HTTP 200 with an empty errors[]."""
        o1 = OrderFactory()
        o2 = OrderFactory()

        resp = api_client.post(
            URL_FINALIZE,
            {"model": "Order", "ids": [str(o1.id), str(o2.id)]},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["finalized_count"] == 2
        assert resp.data["errors"] == []


# ---------------------------------------------------------------------------
# BulkUnfinalizeView
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestBulkUnfinalizeView:
    def test_unfinalizes_orders(self, api_client, tenant):
        """Orders are immutable once finalized (GoBD); the unfinalize endpoint
        must reject the request rather than silently revert numbering.

        ``FinalizedError`` is a ``ConflictError`` -> HTTP 409."""
        o = OrderFactory()
        type(o).objects.filter(pk=o.pk).update(is_finalized=True)
        o.refresh_from_db()

        resp = api_client.post(
            URL_UNFINALIZE,
            {"model": "Order", "ids": [str(o.id)]},
            format="json",
        )
        assert resp.status_code == status.HTTP_409_CONFLICT

    def test_404_if_none_are_finalized(self, api_client, tenant):
        o = OrderFactory()

        resp = api_client.post(
            URL_UNFINALIZE,
            {"model": "Order", "ids": [str(o.id)]},
            format="json",
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_missing_model_returns_400(self, api_client, tenant):
        resp = api_client.post(
            URL_UNFINALIZE,
            {"ids": ["some-id"]},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# BulkFinalizeShareContentView
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestBulkFinalizeShareContentView:
    def _make_composite_id(self, sc):
        return f"{sc.share.year}_{sc.share.delivery_week}_{sc.share_article_id}_{sc.unit}_{sc.size}"

    def test_finalizes_share_content(self, api_client, tenant):
        variation = ShareTypeVariationFactory()
        article = ShareArticleFactory()
        share = ShareFactory(
            year=2026,
            delivery_week=15,
            share_type_variation=variation,
        )
        sc = ShareContentFactory(
            share=share,
            share_article=article,
            unit="KG",
            size="M",
        )
        cid = self._make_composite_id(sc)

        resp = api_client.post(
            URL_FINALIZE_SC,
            {"ids": [cid]},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["finalized_count"] >= 1
        assert "finalization_status" in resp.data

    def test_empty_ids_returns_400(self, api_client, tenant):
        resp = api_client.post(URL_FINALIZE_SC, {"ids": []}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_nonexistent_ids_returns_404(self, api_client, tenant):
        resp = api_client.post(
            URL_FINALIZE_SC,
            {"ids": ["9999_99_nonexistent_KG_M"]},
            format="json",
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def _make_share_content(self, week, article=None):
        share = ShareFactory(
            year=2026,
            delivery_week=week,
            share_type_variation=ShareTypeVariationFactory(),
        )
        return ShareContentFactory(
            share=share,
            share_article=article or ShareArticleFactory(),
            unit="KG",
            size="M",
        )

    def test_partial_success_malformed_id_returns_207(self, api_client, tenant):
        """A valid composite id alongside a malformed one yields 207, the bad
        id in errors[], and the good group still finalized."""
        sc = self._make_share_content(week=15)
        good_cid = self._make_composite_id(sc)

        resp = api_client.post(
            URL_FINALIZE_SC,
            {"ids": [good_cid, "not-a-valid-composite-id"]},
            format="json",
        )

        assert resp.status_code == status.HTTP_207_MULTI_STATUS
        assert resp.data["finalized_count"] == 1
        assert len(resp.data["errors"]) == 1
        sc.refresh_from_db()
        assert sc.is_finalized is True

    def test_db_error_in_one_item_does_not_abort_batch(self, api_client, tenant):
        """REF-3 non-vacuous savepoint guard: one item hits a REAL
        transaction-aborting DB error (not a mocked raise). Without the
        per-item ``with transaction.atomic()`` savepoint the outer atomic is
        poisoned and the whole batch (incl. the final finalization_status
        query) fails with a 500; with it, the good item still finalizes, the
        bad one lands in errors[], and the response is built (207)."""
        # One Share + two distinct articles → two distinct composite groups
        # without spawning a second ShareTypeVariation (which would collide on
        # the SharesDeliveryDay one-open-per-day-number constraint).
        share = ShareFactory(
            year=2026,
            delivery_week=15,
            share_type_variation=ShareTypeVariationFactory(),
        )
        good_sc = ShareContentFactory(
            share=share, share_article=ShareArticleFactory(), unit="KG", size="M"
        )
        bad_sc = ShareContentFactory(
            share=share, share_article=ShareArticleFactory(), unit="KG", size="M"
        )
        good_cid = self._make_composite_id(good_sc)
        bad_cid = self._make_composite_id(bad_sc)

        original_finalize = ShareContent.finalize

        def boom(self, user=None):
            if self.pk == bad_sc.pk:
                # A genuine Postgres error (division by zero) that aborts the
                # transaction — a bare Python ``raise`` would not exercise the
                # savepoint, since it doesn't poison the connection.
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1 / 0")
            return original_finalize(self, user=user)

        with patch.object(ShareContent, "finalize", boom):
            resp = api_client.post(
                URL_FINALIZE_SC,
                {"ids": [bad_cid, good_cid]},
                format="json",
            )

        assert resp.status_code == status.HTTP_207_MULTI_STATUS
        assert any(e["id"] == str(bad_sc.id) for e in resp.data["errors"])
        # The response was still produced (outer transaction NOT poisoned) and
        # the good group finalized despite the sibling's DB error.
        assert "finalization_status" in resp.data
        good_sc.refresh_from_db()
        assert good_sc.is_finalized is True
        bad_sc.refresh_from_db()
        assert bad_sc.is_finalized is False


# ---------------------------------------------------------------------------
# BulkUnfinalizeShareContentView
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestBulkUnfinalizeShareContentView:
    def _make_composite_id(self, sc):
        return f"{sc.share.year}_{sc.share.delivery_week}_{sc.share_article_id}_{sc.unit}_{sc.size}"

    def test_unfinalizes_share_content(self, api_client, tenant):
        variation = ShareTypeVariationFactory()
        article = ShareArticleFactory()
        share = ShareFactory(
            year=2026,
            delivery_week=15,
            share_type_variation=variation,
        )
        sc = ShareContentFactory(
            share=share,
            share_article=article,
            unit="KG",
            size="M",
        )
        # Finalize first
        type(sc).objects.filter(pk=sc.pk).update(is_finalized=True)

        cid = self._make_composite_id(sc)
        resp = api_client.post(
            URL_UNFINALIZE_SC,
            {"ids": [cid]},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert "finalization_status" in resp.data

    def test_empty_ids_returns_400(self, api_client, tenant):
        resp = api_client.post(URL_UNFINALIZE_SC, {"ids": []}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_partial_success_malformed_id_returns_207(self, api_client, tenant):
        """A valid (finalized) composite id alongside a malformed one yields
        207 and the bad id in errors[]; the good group is unfinalized."""
        share = ShareFactory(
            year=2026,
            delivery_week=15,
            share_type_variation=ShareTypeVariationFactory(),
        )
        sc = ShareContentFactory(
            share=share, share_article=ShareArticleFactory(), unit="KG", size="M"
        )
        type(sc).objects.filter(pk=sc.pk).update(is_finalized=True)
        good_cid = self._make_composite_id(sc)

        resp = api_client.post(
            URL_UNFINALIZE_SC,
            {"ids": [good_cid, "not-a-valid-composite-id"]},
            format="json",
        )

        assert resp.status_code == status.HTTP_207_MULTI_STATUS
        assert len(resp.data["errors"]) == 1
        sc.refresh_from_db()
        assert sc.is_finalized is False


# ---------------------------------------------------------------------------
# _get_finalization_status (REF-10 batched aggregation / REF-12 empty group)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestGetFinalizationStatus:
    def _composite_id(self, sc):
        return f"{sc.share.year}_{sc.share.delivery_week}_{sc.share_article_id}_{sc.unit}_{sc.size}"

    def _share(self):
        # A single Share (one ShareTypeVariation → one SharesDeliveryDay).
        # Distinct composite groups are then made by varying the ShareArticle,
        # which avoids the one-open-per-day-number overlap that creating
        # multiple variations would trigger.
        return ShareFactory(
            year=2026,
            delivery_week=10,
            share_type_variation=ShareTypeVariationFactory(),
        )

    def test_fully_finalized_group_is_true(self, tenant):
        sc = ShareContentFactory(
            share=self._share(),
            share_article=ShareArticleFactory(),
            unit="KG",
            size="M",
        )
        type(sc).objects.filter(pk=sc.pk).update(is_finalized=True)
        cid = self._composite_id(sc)
        assert _get_finalization_status([cid]) == {cid: True}

    def test_partially_finalized_group_is_false(self, tenant):
        # Two ShareContent rows sharing the SAME share/article/unit/size form
        # one composite group (the group key ignores delivery_station, which
        # the factory varies — so the unique constraint still permits two
        # rows). Only one is finalized → the group is not fully finalized.
        share = self._share()
        article = ShareArticleFactory()
        sc_a = ShareContentFactory(
            share=share, share_article=article, unit="KG", size="M"
        )
        ShareContentFactory(share=share, share_article=article, unit="KG", size="M")
        type(sc_a).objects.filter(pk=sc_a.pk).update(is_finalized=True)

        cid = self._composite_id(sc_a)
        assert _get_finalization_status([cid]) == {cid: False}

    def test_unknown_group_is_false(self, tenant):
        # Well-formed composite id, zero matching rows (REF-12 empty group).
        assert _get_finalization_status(["2026_52_nope_KG_M"]) == {
            "2026_52_nope_KG_M": False
        }

    def test_malformed_id_is_false(self, tenant):
        assert _get_finalization_status(["garbage"]) == {"garbage": False}

    def test_two_ids_parsing_to_same_group_both_resolve(self, tenant):
        # Two distinct id strings that int()-parse to the SAME group key (here a
        # leading-zero week) must BOTH receive the group's verdict — neither may
        # shadow the other (the per-input-id mapping, not per-group-key).
        sc = ShareContentFactory(
            share=self._share(),
            share_article=ShareArticleFactory(),
            unit="KG",
            size="M",
        )
        type(sc).objects.filter(pk=sc.pk).update(is_finalized=True)
        canonical = self._composite_id(sc)
        variant = (
            f"{sc.share.year}_0{sc.share.delivery_week}"
            f"_{sc.share_article_id}_{sc.unit}_{sc.size}"
        )
        assert canonical != variant
        result = _get_finalization_status([canonical, variant])
        assert result[canonical] is True
        assert result[variant] is True

    def test_single_query_regardless_of_id_count(self, tenant):
        # REF-10 regression guard: a batched aggregation, not 1-2 queries per id.
        # Six distinct composite groups off one Share (distinct articles).
        share = self._share()
        scs = [
            ShareContentFactory(
                share=share, share_article=ShareArticleFactory(), unit="KG", size="M"
            )
            for _ in range(6)
        ]
        for sc in scs:
            type(sc).objects.filter(pk=sc.pk).update(is_finalized=True)
        ids = [self._composite_id(sc) for sc in scs]

        with CaptureQueriesContext(connection) as ctx:
            result = _get_finalization_status(ids)
        assert all(result[cid] for cid in ids)
        # One aggregation query (allow a tiny margin for any savepoint noise);
        # the old per-id version would issue ~2 × len(ids).
        assert len(ctx.captured_queries) <= 2
