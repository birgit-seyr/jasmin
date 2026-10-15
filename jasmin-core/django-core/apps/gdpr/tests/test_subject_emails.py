"""Which email-log rows and login records the GDPR export and the erasure
treat as the subject's, and which recipients the export names.

Only the login's address is out of the subject's hands. Every other address on
their records — ``Member.email``, a customer contact's addresses — counts only
while no other record holds it. These tests point such an address at the
office mailbox and at other people's addresses, and check that neither the
export nor an approved erasure reaches anyone else's records, while the
subject's own mail stays in: mail to their login, to an address only they
hold, and mail linked to one of their records. Mail linked to their records
can have gone to the farm's office or accounting address; the export names
those by category only.
"""

from __future__ import annotations

import uuid

import pytest
from axes.models import AccessFailureLog, AccessLog
from rest_framework.test import APIClient

from apps.commissioning.models import Member
from apps.commissioning.tests.factories import (
    InvoiceResellerFactory,
    JasminUserFactory,
    MemberFactory,
    ResellerFactory,
    SubscriptionFactory,
)
from apps.gdpr.models import DeletionRequestChannel
from apps.gdpr.services import GDPRService
from apps.gdpr.services.subjects import ErasureSubject
from apps.notifications.models import EmailLog
from apps.shared.tenants.models import TenantEmailConfig

# What the erasure writes over a scrubbed EmailLog row.
SCRUBBED_RECIPIENT = "deleted@deleted.invalid"


def _address(name: str) -> str:
    """A fresh address. Committed rows can outlive a test in the shared test
    schema, so a fixed one might already be held by a leftover record."""
    return f"{name}-{uuid.uuid4().hex[:10]}@example.org"


def _mail(recipient: str, subject: str, **fields: str) -> EmailLog:
    return EmailLog.objects.create(
        recipient=recipient, subject=subject, **{"status": "sent", **fields}
    )


def _linked_to(record_type: str, record) -> dict[str, str]:
    return {"related_object_type": record_type, "related_object_id": str(record.pk)}


def _login(username: str) -> AccessLog:
    return AccessLog.objects.create(
        username=username,
        ip_address="10.0.0.1",
        user_agent="UA/test",
        http_accept="*/*",
        path_info="/api/auth/login/",
    )


def _failed_login(username: str) -> AccessFailureLog:
    return AccessFailureLog.objects.create(
        username=username,
        ip_address="10.0.0.2",
        user_agent="UA/test",
        http_accept="*/*",
        path_info="/api/auth/login/",
        locked_out=False,
    )


def _set_office_mailbox(tenant, address: str) -> None:
    tenant.email = address
    tenant.save(update_fields=["email"])


def _set_accounting_address(tenant, address: str) -> None:
    TenantEmailConfig.objects.update_or_create(
        tenant=tenant,
        defaults={"from_email": _address("farm"), "accounting_email": address},
    )


def _exported_mail(user) -> set[str]:
    bundle = GDPRService.get_subject_access_bundle(user)
    return {entry["subject"] for entry in bundle["email_log"]["entries"]}


def _exported_entries(subject: ErasureSubject) -> dict[str, dict]:
    """The export's email-log entries, by subject line."""
    bundle = GDPRService.get_subject_access_bundle_for(subject)
    return {entry["subject"]: entry for entry in bundle["email_log"]["entries"]}


def _downloaded_export(user) -> str:
    """The export as ``user`` downloads it, lower-cased."""
    client = APIClient()
    client.force_authenticate(user=user)
    response = client.get("/api/gdpr/my-data/")
    assert response.status_code == 200
    return response.content.decode().lower()


def _exported_logins(user) -> set[str]:
    history = GDPRService.get_subject_access_bundle(user)["login_history"]
    return {
        row["username"].lower()
        for row in [*history["successful_logins"], *history["failed_attempts"]]
    }


def _erase(user) -> None:
    """Request, confirm and approve ``user``'s erasure."""
    admin = JasminUserFactory(roles=["admin"], email=_address("admin"))
    deletion_request = GDPRService.request_deletion(user)
    GDPRService.confirm_deletion_token(str(deletion_request.token))
    GDPRService.admin_approve_deletion(deletion_request, admin_user=admin)


def _member_with_login(name: str, *, member_email: str | None = None):
    user = JasminUserFactory(roles=["member"], email=_address(name))
    member = MemberFactory(user=user, email=member_email or user.email)
    return user, member


@pytest.mark.django_db
class TestMemberExport:
    def test_the_office_mailbox_as_member_email_exports_none_of_its_mail(self, tenant):
        office = _address("office")
        _set_office_mailbox(tenant, office)
        user, _ = _member_with_login("anna", member_email=office.upper())
        cancelled = MemberFactory(email=_address("berta"))
        _mail(office, "Self-cancellation: Berta", **_linked_to("member", cancelled))
        _mail(office, "Renewal failures: 3")
        _login(office)
        _failed_login(office)
        _mail(user.email, "Welcome, Anna")

        assert _exported_mail(user) == {"Welcome, Anna"}
        assert office not in _exported_logins(user)

    def test_another_members_address_exports_none_of_their_mail(self, tenant):
        other_user, other_member = _member_with_login("berta")
        user, _ = _member_with_login("anna", member_email=other_user.email)
        _mail(other_user.email, "Welcome, Berta", **_linked_to("member", other_member))
        _mail(other_user.email, "Password reset", **_linked_to("user", other_user))
        _mail(other_user.email, "Unlinked mail to Berta")
        _login(other_user.email)
        _failed_login(other_user.email)

        assert _exported_mail(user) == set()
        assert _exported_logins(user) == set()

    def test_an_address_held_with_other_casing_and_spaces_counts_as_held(self, tenant):
        shared = _address("household")
        other = MemberFactory()
        # The office import path can store an address as typed.
        Member.objects.filter(pk=other.pk).update(email=f"  {shared.upper()} ")
        user, _ = _member_with_login("anna", member_email=shared)
        _mail(shared, "Mail to the household")
        _login(shared)

        assert _exported_mail(user) == set()
        assert _exported_logins(user) == set()

    def test_the_members_own_mail_is_exported(self, tenant):
        office = _address("office")
        _set_office_mailbox(tenant, office)
        own_address = _address("anna-private")
        user, member = _member_with_login("anna", member_email=own_address)
        subscription = SubscriptionFactory(member=member)
        someone_else = MemberFactory(email=_address("berta"))
        _mail(user.email, "To the login")
        _mail(own_address, "To the member address")
        _mail(office, "Self-cancellation: Anna", **_linked_to("member", member))
        _mail(
            own_address,
            "A spot is free",
            **_linked_to("subscription", subscription),
        )
        _mail(
            own_address,
            "Linked to a record that is gone",
            related_object_type="member",
            related_object_id="deleted0001",
        )
        _mail(own_address, "About Berta", **_linked_to("member", someone_else))
        _login(user.email)
        _failed_login(own_address.upper())

        assert _exported_mail(user) == {
            "To the login",
            "To the member address",
            "Self-cancellation: Anna",
            "A spot is free",
            "Linked to a record that is gone",
        }
        assert _exported_logins(user) == {user.email, own_address}


@pytest.mark.django_db
class TestCustomerExport:
    def test_another_subjects_address_as_order_email_exports_none_of_their_mail(
        self, tenant
    ):
        other_user, other_member = _member_with_login("berta")
        customer = JasminUserFactory(roles=["customer"], email=_address("shop"))
        ResellerFactory(
            linked_user=customer,
            contact__email=customer.email,
            contact__order_email=other_user.email,
        )
        _mail(other_user.email, "Welcome, Berta", **_linked_to("member", other_member))
        _mail(other_user.email, "Unlinked mail to Berta")
        _login(other_user.email)

        assert _exported_mail(customer) == set()
        assert other_user.email not in _exported_logins(customer)

    def test_the_accounting_mailbox_as_order_email_exports_none_of_its_mail(
        self, tenant
    ):
        accounting = _address("accounting")
        _set_accounting_address(tenant, accounting)
        other_invoice = InvoiceResellerFactory()
        customer = JasminUserFactory(roles=["customer"], email=_address("shop"))
        ResellerFactory(
            linked_user=customer,
            contact__email=customer.email,
            contact__order_email=accounting,
        )
        _mail(accounting, "Invoice 7", **_linked_to("invoice", other_invoice))
        _mail(accounting, "Unlinked mail to accounting")

        assert _exported_mail(customer) == set()

    def test_the_customers_own_mail_is_exported(self, tenant):
        accounting = _address("accounting")
        _set_accounting_address(tenant, accounting)
        customer = JasminUserFactory(roles=["customer"], email=_address("shop"))
        orders = _address("shop-orders")
        billing = _address("shop-billing")
        reseller = ResellerFactory(
            linked_user=customer,
            contact__email=customer.email,
            contact__order_email=orders,
            invoice_email=billing,
        )
        invoice = InvoiceResellerFactory(reseller=reseller)
        _mail(customer.email, "Offer for week 12")
        _mail(orders, "Order confirmation")
        _mail(billing, "Invoice 1", **_linked_to("invoice", invoice))
        _mail(accounting, "Invoice 1 for accounting", **_linked_to("invoice", invoice))
        _mail(billing, "Reminder", **_linked_to("reseller", reseller))

        entries = _exported_entries(ErasureSubject.of_user(customer))

        assert set(entries) == {
            "Offer for week 12",
            "Order confirmation",
            "Invoice 1",
            "Invoice 1 for accounting",
            "Reminder",
        }
        assert entries["Invoice 1"]["recipient"] == billing
        assert entries["Invoice 1 for accounting"]["recipient"] is None
        assert (
            entries["Invoice 1 for accounting"]["recipient_category"]
            == "farm_accounting"
        )


@pytest.mark.django_db
class TestExportedRecipients:
    def test_a_customers_export_never_shows_the_farms_addresses(self, tenant):
        office = _address("office")
        accounting = _address("upload-inbox")
        _set_office_mailbox(tenant, office)
        _set_accounting_address(tenant, accounting)
        customer = JasminUserFactory(roles=["customer"], email=_address("shop"))
        reseller = ResellerFactory(linked_user=customer, contact__email=customer.email)
        invoice = InvoiceResellerFactory(reseller=reseller)
        deletion_request = GDPRService.request_deletion(customer)
        _mail(
            accounting.upper(),
            "Invoice 1",
            status="failed",
            error=f"550 5.1.1 <{accounting}>: recipient rejected",
            provider_message_id="<invoice-1@farm.example>",
            **_linked_to("invoice", invoice),
        )
        _mail(
            office,
            "A deletion request is waiting",
            **_linked_to("gdpr.deletion_request", deletion_request),
        )

        entries = _exported_entries(ErasureSubject.of_user(customer))
        export = _downloaded_export(customer)

        accounting_copy = entries["Invoice 1"]
        assert accounting_copy["recipient"] is None
        assert accounting_copy["recipient_category"] == "farm_accounting"
        assert accounting_copy["status"] == "failed"
        assert accounting_copy["error"] == ""
        assert accounting_copy["provider_message_id"] == ""
        office_notice = entries["A deletion request is waiting"]
        assert office_notice["recipient"] is None
        assert office_notice["recipient_category"] == "farm_office"
        assert "invoice 1" in export
        assert accounting not in export
        assert office not in export

    def test_a_members_export_names_only_the_addresses_on_their_records(self, tenant):
        office = _address("office")
        _set_office_mailbox(tenant, office)
        household = _address("household")
        user, member = _member_with_login("anna")
        Member.objects.filter(pk=member.pk).update(email_2=household)
        MemberFactory(email=household)
        deletion_request = GDPRService.request_deletion(user)
        mailbox_full = f"452 4.2.2 <{user.email}>: mailbox full"
        _mail(
            user.email,
            "Welcome, Anna",
            status="failed",
            error=mailbox_full,
            provider_message_id="<welcome@farm.example>",
            **_linked_to("member", member),
        )
        _mail(household, "Pickup moved", **_linked_to("member", member))
        _mail(office, "Self-cancellation: Anna", **_linked_to("member", member))
        _mail(office, "Consent withdrawn", **_linked_to("member", member))
        _mail(
            office,
            "A deletion request is waiting",
            **_linked_to("gdpr.deletion_request", deletion_request),
        )
        # An address her record held before.
        _mail(_address("anna-before"), "Your share", **_linked_to("member", member))

        entries = _exported_entries(ErasureSubject.of_user(user))

        welcome = entries["Welcome, Anna"]
        assert welcome["recipient"] == user.email
        assert welcome["recipient_category"] == "data_subject"
        assert welcome["error"] == mailbox_full
        assert welcome["provider_message_id"] == "<welcome@farm.example>"
        # Another member holds it too, but her record lists it.
        assert entries["Pickup moved"]["recipient"] == household
        assert entries["Pickup moved"]["recipient_category"] == "data_subject"
        for office_notice in (
            "Self-cancellation: Anna",
            "Consent withdrawn",
            "A deletion request is waiting",
        ):
            assert entries[office_notice]["recipient"] is None
            assert entries[office_notice]["recipient_category"] == "farm_office"
        assert entries["Your share"]["recipient"] is None
        assert entries["Your share"]["recipient_category"] == "other"
        assert office not in _downloaded_export(user)

    def test_the_address_a_deletion_request_was_filed_under_is_named(self, tenant):
        filed_under = _address("anna-before")
        member = MemberFactory(email=filed_under)
        admin = JasminUserFactory(roles=["admin"], email=_address("admin"))
        deletion_request = GDPRService.file_deletion_for_subject(
            ErasureSubject(member=member),
            admin_user=admin,
            channel=DeletionRequestChannel.LETTER,
        )
        Member.objects.filter(pk=member.pk).update(email=_address("anna-now"))
        _mail(
            filed_under,
            "Your deletion request was rejected",
            **_linked_to("gdpr.deletion_request", deletion_request),
        )

        entries = _exported_entries(
            ErasureSubject(member=Member.objects.get(pk=member.pk))
        )

        rejected = entries["Your deletion request was rejected"]
        assert rejected["recipient"] == filed_under
        assert rejected["recipient_category"] == "data_subject"


@pytest.mark.django_db
class TestErasure:
    def test_erasing_a_member_with_the_office_mailbox_leaves_its_records(self, tenant):
        office = _address("office")
        _set_office_mailbox(tenant, office)
        user, member = _member_with_login("anna", member_email=office)
        cancelled = MemberFactory(email=_address("berta"))
        office_mail = [
            _mail(
                office, "Self-cancellation: Berta", **_linked_to("member", cancelled)
            ),
            _mail(office, "Renewal failures: 3"),
        ]
        office_login = _login(office)
        office_failure = _failed_login(office)
        own_mail = [
            _mail(user.email, "Welcome, Anna"),
            _mail(office, "Self-cancellation: Anna", **_linked_to("member", member)),
        ]

        _erase(user)

        for row in office_mail:
            row.refresh_from_db()
            assert row.recipient == office
        assert {row.subject for row in office_mail} == {
            "Self-cancellation: Berta",
            "Renewal failures: 3",
        }
        assert AccessLog.objects.filter(pk=office_login.pk).exists()
        assert AccessFailureLog.objects.filter(pk=office_failure.pk).exists()
        for row in own_mail:
            row.refresh_from_db()
            assert row.recipient == SCRUBBED_RECIPIENT

    def test_erasing_a_member_with_another_members_address_leaves_their_records(
        self, tenant
    ):
        other_user, other_member = _member_with_login("berta")
        user, _ = _member_with_login("anna", member_email=other_user.email)
        their_mail = [
            _mail(
                other_user.email, "Welcome, Berta", **_linked_to("member", other_member)
            ),
            _mail(other_user.email, "Unlinked mail to Berta"),
        ]
        their_login = _login(other_user.email)
        own_mail = _mail(user.email, "Welcome, Anna")
        own_login = _login(user.email)

        _erase(user)

        for row in their_mail:
            row.refresh_from_db()
            assert row.recipient == other_user.email
            assert row.subject != "Gelöscht"
        assert AccessLog.objects.filter(pk=their_login.pk).exists()
        own_mail.refresh_from_db()
        assert own_mail.recipient == SCRUBBED_RECIPIENT
        assert not AccessLog.objects.filter(pk=own_login.pk).exists()

    def test_erasing_a_customer_with_another_subjects_order_email_leaves_their_records(
        self, tenant
    ):
        other_user, other_member = _member_with_login("berta")
        customer = JasminUserFactory(roles=["customer"], email=_address("shop"))
        ResellerFactory(
            linked_user=customer,
            contact__email=customer.email,
            contact__order_email=other_user.email,
        )
        their_mail = _mail(
            other_user.email, "Welcome, Berta", **_linked_to("member", other_member)
        )
        their_failure = _failed_login(other_user.email)

        _erase(customer)

        their_mail.refresh_from_db()
        assert their_mail.recipient == other_user.email
        assert their_mail.subject == "Welcome, Berta"
        assert AccessFailureLog.objects.filter(pk=their_failure.pk).exists()

    def test_the_preview_counts_the_rows_the_erasure_scrubs(self, tenant):
        office = _address("office")
        _set_office_mailbox(tenant, office)
        user, member = _member_with_login("anna", member_email=office)
        office_mail = _mail(office, "Renewal failures: 3")
        own_mail = [
            _mail(user.email, "Welcome, Anna"),
            _mail(office, "Self-cancellation: Anna", **_linked_to("member", member)),
        ]

        preview = GDPRService.preview_deletion(user)
        email_log = next(
            entry
            for entry in preview["models"]
            if entry["model"] == "notifications.EmailLog"
        )
        _erase(user)

        assert email_log["row_count"] == len(own_mail)
        for row in own_mail:
            row.refresh_from_db()
            assert row.recipient == SCRUBBED_RECIPIENT
        office_mail.refresh_from_db()
        assert office_mail.recipient == office
