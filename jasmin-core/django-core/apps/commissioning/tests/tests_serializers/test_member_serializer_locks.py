"""Tests for the ``MemberSerializer`` post-admin-confirmation lock.

Once a Member is admin-confirmed (Mitglied der Genossenschaft per
GenG), two fields become legally fixed:

  * ``birth_date`` — biological fact + GDPR-classified PII. Edits
    after confirmation would falsify the audit trail.
  * ``is_trial``  — the trial → full conversion is one-way; flipping
    back would orphan the assigned Mitgliedsnummer and
    Eintrittsdatum.

The frontend disables these cells when ``record.admin_confirmed`` is
True. That UI lock is a usability hint, not the security boundary —
a tech-savvy office user could POST directly to the API. These tests
lock the SERVER-SIDE guard so that path also fails closed.

Unaffected fields (name, address, email, IBAN, …) remain editable
forever — real life requires those updates and ``django-auditlog``
already records the diffs.
"""

from __future__ import annotations

import datetime

import pytest
from django.utils import timezone

from apps.commissioning.errors import LockedAfterAdminConfirmation
from apps.commissioning.serializers import (
    CoopShareSerializer,
    MemberSelfReadSerializer,
    MemberSerializer,
)
from apps.commissioning.tests.factories import (
    CoopShareFactory,
    JasminUserFactory,
    MemberFactory,
)


@pytest.mark.django_db
class TestLocksAfterAdminConfirmation:
    """The lock fires only when ``admin_confirmed=True``. Same field
    edits are allowed on an unconfirmed member, and on a confirmed
    member when the value isn't actually changing (PATCH that includes
    the field but with the existing value — a frontend that re-sends
    the whole row shouldn't trip the guard)."""

    def _make_confirmed(self, **overrides):
        defaults = {
            "is_trial": False,
            "birth_date": datetime.date(1985, 3, 15),
            "admin_confirmed": True,
            "admin_confirmed_at": timezone.now(),
        }
        defaults.update(overrides)
        return MemberFactory(**defaults)

    def test_birth_date_edit_rejected_after_confirmation(self, tenant):
        member = self._make_confirmed()
        serializer = MemberSerializer(
            instance=member,
            data={"birth_date": datetime.date(1990, 1, 1)},
            partial=True,
        )
        with pytest.raises(LockedAfterAdminConfirmation) as exc_info:
            # ``LockedAfterAdminConfirmation`` is a JasminError, not a
            # DRF ValidationError — it propagates straight out of
            # ``is_valid()`` instead of being caught into ``.errors``.
            serializer.is_valid(raise_exception=False)
        assert "birth_date" in exc_info.value.details["locked_fields"]

    def test_is_trial_edit_rejected_after_confirmation(self, tenant):
        member = self._make_confirmed(is_trial=False)
        serializer = MemberSerializer(
            instance=member,
            data={"is_trial": True},
            partial=True,
        )
        with pytest.raises(LockedAfterAdminConfirmation) as exc_info:
            serializer.is_valid(raise_exception=False)
        assert "is_trial" in exc_info.value.details["locked_fields"]

    def test_both_locked_fields_reported_together(self, tenant):
        member = self._make_confirmed()
        serializer = MemberSerializer(
            instance=member,
            data={
                "birth_date": datetime.date(1990, 1, 1),
                "is_trial": True,
            },
            partial=True,
        )
        with pytest.raises(LockedAfterAdminConfirmation) as exc_info:
            serializer.is_valid(raise_exception=False)
        fields = exc_info.value.details["locked_fields"]
        assert set(fields) == {"birth_date", "is_trial"}

    def test_unchanged_value_resubmit_is_allowed(self, tenant):
        """A frontend that re-PATCHes the whole row with unchanged
        ``birth_date`` / ``is_trial`` values must not be rejected —
        the guard fires on actual diffs, not on field presence."""
        member = self._make_confirmed()
        serializer = MemberSerializer(
            instance=member,
            data={
                "birth_date": member.birth_date,
                "is_trial": member.is_trial,
                "first_name": "NewName",
            },
            partial=True,
        )
        assert serializer.is_valid(raise_exception=False), serializer.errors

    def test_editable_fields_remain_editable(self, tenant):
        """Name + address + contact + bank fields stay editable on a
        confirmed member — these legitimately change in real life and
        auditlog tracks the history."""
        member = self._make_confirmed()
        serializer = MemberSerializer(
            instance=member,
            data={
                "first_name": "Maria",
                "last_name": "Müller-Neumann",
                "address": "Hauptstraße 42",
                "email": "maria@example.com",
                "is_active": True,
                "note": "Heiratet im Mai.",
            },
            partial=True,
        )
        assert serializer.is_valid(raise_exception=False), serializer.errors


@pytest.mark.django_db
class TestPreConfirmationFieldsRemainEditable:
    """Before admin confirmation, all fields including ``birth_date``
    and ``is_trial`` must be editable — that's the whole point of the
    pre-confirmation correction window."""

    def test_birth_date_edit_allowed_before_confirmation(self, tenant):
        member = MemberFactory(
            birth_date=datetime.date(1985, 3, 15),
            admin_confirmed=False,
        )
        serializer = MemberSerializer(
            instance=member,
            data={"birth_date": datetime.date(1990, 1, 1)},
            partial=True,
        )
        assert serializer.is_valid(raise_exception=False), serializer.errors

    def test_is_trial_edit_allowed_before_confirmation(self, tenant):
        member = MemberFactory(is_trial=False, admin_confirmed=False)
        serializer = MemberSerializer(
            instance=member,
            data={"is_trial": True},
            partial=True,
        )
        assert serializer.is_valid(raise_exception=False), serializer.errors


@pytest.mark.django_db
class TestUnconditionallyReadOnlyFields:
    """Fields that DRF must silently drop from PATCH payloads — owned
    by dedicated services / flows whose invariants a generic PATCH
    would bypass. Locks ``Meta.read_only_fields`` on the serializer.

    DRF's read-only contract: input for these fields is silently
    discarded (NOT raised as an error), so an over-eager frontend
    that sends the whole row is tolerated. The fact under test is
    that the value never lands in ``validated_data`` and therefore
    never reaches ``.update()`` / ``.save()``.
    """

    @pytest.mark.parametrize(
        "field,value",
        [
            ("member_number", 99999),
            ("entry_date", datetime.date(1990, 1, 1)),
            ("sepa_consent", timezone.now()),
            ("privacy_consent", timezone.now()),
            ("withdrawal_consent", timezone.now()),
            ("cancelled_at", timezone.now()),
            ("cancelled_effective_at", datetime.date(2030, 12, 31)),
            ("admin_confirmed", True),
            ("admin_confirmed_at", timezone.now()),
            ("trial_converted_at", timezone.now()),
        ],
    )
    def test_field_is_silently_dropped_from_payload(self, tenant, field, value):
        member = MemberFactory(admin_confirmed=False)
        serializer = MemberSerializer(
            instance=member,
            data={field: value, "first_name": "ChangeMe"},
            partial=True,
        )
        assert serializer.is_valid(raise_exception=False), serializer.errors
        # Read-only fields are silently absent from validated_data.
        assert field not in serializer.validated_data
        # Other writes in the same payload still take effect.
        assert serializer.validated_data.get("first_name") == "ChangeMe"


@pytest.mark.django_db
class TestMemberSelfReadOmitsPlaintextSepa:
    """MEM-6: a member reading their OWN row must NOT receive plaintext IBAN /
    account_owner / sepa_consent. The encrypted columns decrypt transparently on
    access, so a plain ModelSerializer would echo them — only boolean ``*_stored``
    indicators are exposed (mirrors ``MyMemberDataReadSerializer``)."""

    def test_plaintext_sepa_fields_absent(self, tenant):
        member = MemberFactory(
            iban="AT611904300234573201",
            account_owner="Maria Muster",
            sepa_consent=timezone.now(),
        )
        data = MemberSelfReadSerializer(instance=member).data
        assert "iban" not in data
        assert "account_owner" not in data
        assert "sepa_consent" not in data
        # The boolean indicators ARE present and reflect stored state.
        assert data["iban_stored"] is True
        assert data["account_owner_stored"] is True

    def test_stored_indicators_false_when_unset(self, tenant):
        member = MemberFactory(iban=None, account_owner=None)
        data = MemberSelfReadSerializer(instance=member).data
        assert data["iban_stored"] is False
        assert data["account_owner_stored"] is False


@pytest.mark.django_db
class TestOfficeMemberSerializerMasksSepa:
    """The office full serializer accepts the decrypted SEPA columns on write
    (the IBANValidator still runs) but only echoes a masked representation on
    read — a bulk members list must not exfiltrate every IBAN."""

    def test_plaintext_absent_masked_present(self, tenant):
        member = MemberFactory(
            iban="DE89370400440532013000",
            account_owner="Ada Lovelace",
        )
        data = MemberSerializer(instance=member).data
        # Decrypted values never echoed…
        assert "iban" not in data
        assert "account_owner" not in data
        # …only the masked companions.
        assert data["iban_masked"] == "DE •••• 3000"
        assert data["account_owner_masked"] == "A•• L•••••••"

    def test_masked_empty_when_unset(self, tenant):
        member = MemberFactory(iban=None, account_owner=None)
        data = MemberSerializer(instance=member).data
        assert data["iban_masked"] == ""
        assert data["account_owner_masked"] == ""

    def test_iban_still_writable(self, tenant):
        """write_only means hidden on read, NOT rejected on write — the office
        SEPA edit path must still persist a new IBAN (validator runs)."""
        member = MemberFactory(iban=None)
        serializer = MemberSerializer(
            instance=member,
            data={"iban": "DE89370400440532013000"},
            partial=True,
        )
        assert serializer.is_valid(raise_exception=False), serializer.errors
        assert serializer.validated_data.get("iban") == "DE89370400440532013000"


@pytest.mark.django_db
class TestMemberUserLinkIsReadOnly:
    """MEM-7: the role-bearing member↔user link must never be set via a generic
    PATCH — relinking/unlinking it would strand ``Role.MEMBER`` on the old user.
    Linking is owned by the create-path service; the field is read-only here."""

    def test_user_field_is_read_only(self, tenant):
        assert MemberSerializer().fields["user"].read_only is True

    def test_user_silently_dropped_from_payload(self, tenant):
        member = MemberFactory(admin_confirmed=False)
        other = JasminUserFactory()
        serializer = MemberSerializer(
            instance=member,
            data={"user": other.pk, "first_name": "ChangeMe"},
            partial=True,
        )
        assert serializer.is_valid(raise_exception=False), serializer.errors
        assert "user" not in serializer.validated_data
        assert serializer.validated_data.get("first_name") == "ChangeMe"


@pytest.mark.django_db
class TestCoopShareSerializerLocksAuditFields:
    """MEM-8: ``CoopShareSerializer`` was ``fields="__all__"`` with no
    ``read_only_fields`` — the GenG §30/§31 audit trail plus the
    cancellation / confirmation / payment columns were all freely PATCHable.
    They're owned by dedicated services and must be read-only on the API."""

    @pytest.mark.parametrize(
        "field",
        [
            "cancelled_at",
            "cancelled_effective_at",
            "cancelled_by",
            "admin_confirmed",
            "admin_confirmed_at",
            "admin_confirmed_by",
            "admin_rejected_at",
            "admin_rejection_reason",
            "paid_at",
        ],
    )
    def test_audit_field_is_read_only(self, tenant, field):
        serializer = CoopShareSerializer()
        # The field must EXIST on the serializer (guards against a false green
        # where a renamed field is "absent" rather than "locked")…
        assert field in serializer.fields, f"{field} is not a CoopShare field"
        # …and be read-only.
        assert serializer.fields[field].read_only is True

    def test_amount_remains_writable(self, tenant):
        # Sanity: the lockdown didn't accidentally freeze a legitimately
        # editable column (the equity amount is still settable on create/edit).
        share = CoopShareFactory()
        serializer = CoopShareSerializer(
            instance=share, data={"amount_of_coop_shares": 3}, partial=True
        )
        assert serializer.is_valid(raise_exception=False), serializer.errors
        assert serializer.validated_data.get("amount_of_coop_shares") == 3
