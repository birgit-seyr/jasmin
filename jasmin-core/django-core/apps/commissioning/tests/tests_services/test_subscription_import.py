"""Subscription CSV import — FK resolution by natural key, draft creation,
dry-run, and per-row error isolation.

Subscriptions reference their FKs (member / variation via share_type+size /
payment-cycle / station-day) by human-readable natural keys, resolved by
``SubscriptionImportSerializer``. Rows land as unconfirmed drafts.
"""

from __future__ import annotations

import datetime

import pytest
import time_machine

from apps.commissioning.models import PaymentCycle, Subscription
from apps.commissioning.models.choices import PaymentCycleOptions
from apps.commissioning.services.data_import import import_rows_from_csv
from apps.commissioning.tests.factories import (
    MemberFactory,
    ShareTypeVariationFactory,
)

_FROZEN = datetime.date(2026, 1, 5)  # Monday, before the imported dates
_VALID_FROM = "2026-01-05"  # Monday
_VALID_UNTIL = "2026-12-27"  # Sunday

_HEADER = (
    "member_number,share_type,size,payment_cycle,valid_from,"
    "valid_until,quantity,is_trial"
)


def _csv(*rows: str) -> bytes:
    # 3-row template layout: row 0 titles, row 1 the dataIndex schema (the one
    # the importer reads), row 2 type hints — then the data rows. Using the same
    # header text for the ignored title/hint rows keeps it unambiguous regardless
    # of how many data rows follow.
    return ("\n".join([_HEADER, _HEADER, _HEADER, *rows]) + "\n").encode("utf-8")


@pytest.mark.django_db
class TestSubscriptionImport:
    @pytest.fixture(autouse=True)
    def _freeze(self):
        with time_machine.travel(_FROZEN, tick=False):
            yield

    def _reference_data(self):
        """A member + one variation (active at valid_from) + the MONTHLY cycle.

        Returns the (share_type name, size) natural key the CSV must reference.
        """
        member = MemberFactory(member_number=4242)
        # Factory default valid_from is 2026-01-05 (== the share type's start and
        # our subscription valid_from), so the variation is active on that date.
        variation = ShareTypeVariationFactory()
        PaymentCycle.objects.get_or_create(choice=PaymentCycleOptions.MONTHLY)
        return member, variation, variation.share_type.name, variation.size

    def test_imports_draft_with_resolved_fks(self, tenant):
        member, variation, st, size = self._reference_data()
        result = import_rows_from_csv(
            "subscription",
            _csv(f"4242,{st},{size},MONTHLY,{_VALID_FROM},{_VALID_UNTIL},1,false"),
        )
        assert result.successful == 1, result.errors
        assert result.failed == 0
        sub = Subscription.objects.get()
        assert sub.member_id == member.pk
        assert sub.share_type_variation_id == variation.pk
        assert sub.payment_cycle.choice == PaymentCycleOptions.MONTHLY
        # Draft — confirmation (and materialisation/billing) is a separate step.
        assert sub.admin_confirmed is False

    def test_dry_run_resolves_but_persists_nothing(self, tenant):
        _, _, st, size = self._reference_data()
        result = import_rows_from_csv(
            "subscription",
            _csv(f"4242,{st},{size},MONTHLY,{_VALID_FROM},{_VALID_UNTIL},1,false"),
            dry_run=True,
        )
        assert result.successful == 1, result.errors
        assert Subscription.objects.count() == 0

    def test_dry_run_surfaces_model_level_failure(self, tenant):
        # A faithful dry-run runs the SAME persistence path (rolled back), so a
        # row the serializer accepts but the MODEL rejects must show as an error,
        # not a false success. ``valid_from`` on a Tuesday passes DRF's DateField
        # but fails ``TimeBoundMixin`` (Monday rule) at save().
        _, _, st, size = self._reference_data()
        tuesday = "2026-01-06"
        result = import_rows_from_csv(
            "subscription",
            _csv(f"4242,{st},{size},MONTHLY,{tuesday},{_VALID_UNTIL},1,false"),
            dry_run=True,
        )
        assert result.successful == 0, result.results
        assert result.failed == 1
        assert "monday" in result.errors[0]["error"].lower()
        assert Subscription.objects.count() == 0

    def test_valid_until_is_required(self, tenant):
        # Open-ended subscriptions are forbidden by the domain, so a blank
        # valid_until is a clean per-row validation error (not a model crash).
        _, _, st, size = self._reference_data()
        result = import_rows_from_csv(
            "subscription",
            _csv(f"4242,{st},{size},MONTHLY,{_VALID_FROM},,1,false"),
        )
        assert result.successful == 0
        assert result.failed == 1
        assert "valid_until" in result.errors[0]["error"].lower()
        assert Subscription.objects.count() == 0

    def test_reimport_same_subscription_number_is_skipped(self, tenant):
        # subscription_number is the renewal-chain id (not unique), so re-import
        # can't be blocked by a DB constraint — the importer dedups on
        # (member, subscription_number, valid_from) so uploading the same file
        # twice does not double the drafts.
        _, _, st, size = self._reference_data()
        header = (
            "member_number,share_type,size,payment_cycle,valid_from,"
            "valid_until,quantity,is_trial,subscription_number"
        )
        row = f"4242,{st},{size},MONTHLY,{_VALID_FROM},{_VALID_UNTIL},1,false,7001"
        csv_bytes = ("\n".join([header, header, header, row]) + "\n").encode("utf-8")

        first = import_rows_from_csv("subscription", csv_bytes)
        assert first.successful == 1, first.errors

        second = import_rows_from_csv("subscription", csv_bytes)
        assert second.successful == 0
        assert second.failed == 1
        assert "already" in second.errors[0]["error"].lower()
        assert Subscription.objects.count() == 1

    def test_unresolved_member_is_a_row_error_not_a_crash(self, tenant):
        _, _, st, size = self._reference_data()
        result = import_rows_from_csv(
            "subscription",
            _csv(f"9999,{st},{size},MONTHLY,{_VALID_FROM},{_VALID_UNTIL},1,false"),
        )
        assert result.successful == 0
        assert result.failed == 1
        assert "member" in result.errors[0]["error"].lower()
        assert Subscription.objects.count() == 0

    def test_unknown_share_type_is_a_row_error(self, tenant):
        _, _, _, size = self._reference_data()
        result = import_rows_from_csv(
            "subscription",
            _csv(f"4242,Nope,{size},MONTHLY,{_VALID_FROM},{_VALID_UNTIL},1,false"),
        )
        assert result.failed == 1
        assert "share type" in result.errors[0]["error"].lower()

    def test_per_row_isolation_good_and_bad_rows(self, tenant):
        _, _, st, size = self._reference_data()
        result = import_rows_from_csv(
            "subscription",
            _csv(
                f"4242,{st},{size},MONTHLY,{_VALID_FROM},{_VALID_UNTIL},1,false",
                f"9999,{st},{size},MONTHLY,{_VALID_FROM},{_VALID_UNTIL},1,false",
            ),
        )
        assert result.successful == 1
        assert result.failed == 1
        assert Subscription.objects.count() == 1
