"""``SubscriptionSerializer`` resolves its two id fields before the service does.

``member`` and ``share_type_variation`` are flat writable id strings that get
assigned straight to the FK columns (create resolves them, update sets
``*_id``). Without a serializer-side existence check an unknown id reaches the
database and surfaces as a generic integrity conflict on the update path, so
each one is validated here and reported as its own named 404.
"""

from __future__ import annotations

import datetime

import pytest

from apps.commissioning.errors import MemberNotFound, ShareTypeVariationNotFound
from apps.commissioning.serializers import SubscriptionSerializer
from apps.commissioning.tests.factories import (
    MemberFactory,
    ShareTypeVariationFactory,
    SubscriptionFactory,
)


@pytest.mark.django_db
class TestSubscriptionForeignKeyIdsAreResolved:
    def _draft(self, **overrides):
        # admin_confirmed=False so the confirmation lockdown doesn't pre-empt
        # the field-level checks under test.
        defaults = {
            "valid_from": datetime.date(2026, 1, 5),  # Monday
            "valid_until": datetime.date(2026, 12, 27),  # Sunday
            "admin_confirmed": False,
        }
        defaults.update(overrides)
        return SubscriptionFactory(**defaults)

    def test_unknown_member_id_is_rejected_by_name(self, tenant):
        serializer = SubscriptionSerializer(data={"member": "does-not-exist"})
        with pytest.raises(MemberNotFound) as excinfo:
            serializer.is_valid()
        assert excinfo.value.code == "member.not_found"
        assert excinfo.value.field == "member"

    def test_unknown_variation_id_is_rejected_by_name(self, tenant):
        member = MemberFactory()
        serializer = SubscriptionSerializer(
            data={
                "member": str(member.id),
                "share_type_variation": "does-not-exist",
            }
        )
        with pytest.raises(ShareTypeVariationNotFound) as excinfo:
            serializer.is_valid()
        assert excinfo.value.code == "share_type_variation.not_found"
        assert excinfo.value.field == "share_type_variation"

    def test_patch_with_an_unknown_member_is_rejected(self, tenant):
        """An unknown member id on the update path is refused the same way as
        on create."""
        subscription = self._draft()
        serializer = SubscriptionSerializer(
            instance=subscription,
            data={"member": "does-not-exist"},
            partial=True,
        )
        with pytest.raises(MemberNotFound):
            serializer.is_valid()
        subscription.refresh_from_db()
        assert subscription.member_id is not None

    def test_patch_with_an_unknown_variation_is_rejected(self, tenant):
        subscription = self._draft()
        serializer = SubscriptionSerializer(
            instance=subscription,
            data={"share_type_variation": "does-not-exist"},
            partial=True,
        )
        with pytest.raises(ShareTypeVariationNotFound):
            serializer.is_valid()

    def test_a_known_member_id_passes(self, tenant):
        """The present case: a real id validates and reaches the service as the
        flat id string it assigns to ``member_id``."""
        subscription = self._draft()
        other_member = MemberFactory()
        serializer = SubscriptionSerializer(
            instance=subscription,
            data={"member": str(other_member.id)},
            partial=True,
        )
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["member"] == other_member.id

    def test_a_known_variation_id_passes(self, tenant):
        subscription = self._draft()
        variation = ShareTypeVariationFactory()
        serializer = SubscriptionSerializer(
            instance=subscription,
            data={"share_type_variation": str(variation.id)},
            partial=True,
        )
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["share_type_variation"] == variation.id
