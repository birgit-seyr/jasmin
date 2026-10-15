"""Which email-log rows and login records are a data subject's.

The Art. 15 export and the Art. 17 erasure find a subject's email log and
login history by address. Of the addresses on a subject's records only the
login's is out of their hands: it is set when the login is created, through an
invitation or a confirmed registration, and never changes. The others are typed
in — customers edit their contact's addresses themselves, the office enters
what it is told, and two members may share one ``Member.email`` on purpose — so
any of them can be another person's address or the office mailbox. Searched by
as they are, they would hand that person's email history to the subject, or
wipe it with the subject's erasure.

So the search uses the login's address and the addresses its invitations went
to, and any other address of the subject's only while no record outside the
subject holds it: no other login, member, contact or reseller, and none of the
tenant's own addresses. An email-log row linked to one of the subject's records
is theirs whoever it went to; one linked to another person's record never is.
A row whose linked record no longer exists counts by its address alone.

Whoever a linked row went to, its subject line is the subject's data, but its
recipient may not be: the office gets a notice when a member cancels, and the
accounting address, often a document-upload inbox, a copy of every invoice.
The export names a recipient only when the address is on the subject's own
records, which it lists anyway, and every other one by its category.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from enum import StrEnum
from functools import reduce
from operator import or_
from typing import Any

from django.contrib.auth import get_user_model
from django.db.models import CharField, Q, QuerySet
from django.db.models.functions import Cast, Lower, Trim

from apps.commissioning.models import (
    ContactEntity,
    DeliveryNoteReseller,
    InvoiceReseller,
    Member,
    Reseller,
    Subscription,
    UserInvitation,
)
from apps.shared.tenant_lookup import tenants_with_schema
from apps.shared.tenants.models import TenantEmailConfig
from core.tenant_db import connection

from ..models import DeletionRequest
from .subjects import ErasureSubject


def _ci_username_q(emails: Iterable[str]) -> Q:
    """OR of case-insensitive ``username`` matches for every address.

    ``django-axes`` keys its rows by the lower-cased login address
    (``apps.accounts.services.login_lockout.axes_username``), while an
    address may be stored as ``Foo@Bar.com``. Matching it with
    ``username__in`` would miss the rows — leaving login records behind
    on an Art. 17 deletion, or overlooking them in an Art. 15 export.
    ``username__iexact`` per address closes the gap; email addresses are
    case-insensitive identifiers, so this is the correct comparison."""
    query = Q()
    for email in emails:
        query |= Q(username__iexact=email)
    return query


def _ci_recipient_q(emails: Iterable[str]) -> Q:
    """OR of case-insensitive ``recipient`` matches for every address.

    ``EmailLog.recipient`` stores whatever casing the send used, and the
    secondary address columns (``Member.email_2``/``email_3``, reseller
    contact fields) are unvalidated CharFields — so mixed-case rows exist
    on both sides of the match. A case-sensitive ``recipient__in`` would
    let those rows survive an Art. 17 scrub, or hide them from an
    Art. 15 export; ``recipient__iexact`` per address mirrors
    ``_ci_username_q``."""
    query = Q()
    for email in emails:
        query |= Q(recipient__iexact=email)
    return query


def _normalized(address: str | None) -> str:
    return (address or "").strip().lower()


class RecipientCategory(StrEnum):
    """Who an email-log row of the subject went to, as the export names it."""

    # An address on the subject's own records.
    DATA_SUBJECT = "data_subject"
    # The farm's office or order mailbox, or its sender or reply-to address.
    FARM_OFFICE = "farm_office"
    # The farm's accounting address.
    FARM_ACCOUNTING = "farm_accounting"
    # Any other address, such as one the subject's records no longer hold.
    OTHER = "other"


@dataclass(frozen=True)
class SubjectEmailKeys:
    """What a subject's email-log rows and login records are found by, and
    which recipients of those rows the export may name.

    Built by :func:`subject_email_keys` before an erasure scrubs the records it
    is read from."""

    # Trimmed and lower-cased, as are the addresses below.
    addresses: frozenset[str]
    # The email-log rows linked to one of the subject's records; None when the
    # subject has no record a row can be linked to.
    own_rows: Q | None
    # The email-log rows linked to an existing record of anyone else.
    others_rows: Q
    # Every address the export lists on the subject's own records, whether or
    # not another record holds it too.
    record_addresses: frozenset[str]
    # The farm's own addresses, by the category each stands for.
    farm_addresses: Mapping[str, RecipientCategory]

    def recipient_category(self, recipient: str) -> RecipientCategory:
        """Who a row sent to ``recipient`` went to. The export names the
        address only for :attr:`RecipientCategory.DATA_SUBJECT`."""
        address = _normalized(recipient)
        if address in self.record_addresses:
            return RecipientCategory.DATA_SUBJECT
        return self.farm_addresses.get(address, RecipientCategory.OTHER)

    def email_log_q(self) -> Q | None:
        """The subject's email-log rows: the ones linked to their records, and
        the ones sent to one of their addresses that aren't linked to anyone
        else's. None when there is nothing to search by — an empty ``Q()``
        would match every row."""
        queries: list[Q] = [] if self.own_rows is None else [self.own_rows]
        if self.addresses:
            queries.append(_ci_recipient_q(self.addresses) & ~self.others_rows)
        return reduce(or_, queries) if queries else None

    def login_q(self) -> Q | None:
        """The subject's django-axes records, by the login address they are
        keyed under; None when the subject has no address."""
        return _ci_username_q(self.addresses) if self.addresses else None


def subject_email_keys(subject: ErasureSubject) -> SubjectEmailKeys:
    """The keys the Art. 15 export and the Art. 17 erasure find ``subject``'s
    email log and login history by. See the module docstring."""
    owned = _owned_records(subject)
    login_addresses = _login_addresses(subject)
    other_addresses = _record_addresses(subject) - login_addresses
    farm_addresses = _farm_addresses()
    held_elsewhere = _held_elsewhere(other_addresses, subject, farm_addresses.keys())
    own_rows, others_rows = _record_links(owned)
    return SubjectEmailKeys(
        addresses=frozenset(login_addresses | (other_addresses - held_elsewhere)),
        own_rows=own_rows,
        others_rows=others_rows,
        record_addresses=frozenset(
            login_addresses | other_addresses | _requested_addresses(owned)
        ),
        farm_addresses=farm_addresses,
    )


def _record_links(owned: dict[str, Q]) -> tuple[Q | None, Q]:
    """The email-log rows linked to one of the subject's records, ``owned`` by
    kind, or None when the subject has none; and the ones linked to an existing
    record of anyone else."""
    own_rows: list[Q] = []
    others_rows: list[Q] = []
    for record_type, records in _linkable_records().items():
        subjects_own = owned.get(record_type)
        others = records
        if subjects_own is not None:
            own_rows.append(_rows_linked_to(record_type, records.filter(subjects_own)))
            others = records.exclude(subjects_own)
        others_rows.append(_rows_linked_to(record_type, others))
    return (reduce(or_, own_rows) if own_rows else None), reduce(or_, others_rows)


def _linkable_records() -> dict[str, QuerySet[Any]]:
    """The records an email-log row can be linked to that each belong to one
    data subject, by the ``related_object_type`` naming their kind."""
    return {
        "user": get_user_model().objects.all(),
        "member": Member.objects.all(),
        "subscription": Subscription.objects.all(),
        "reseller": Reseller.objects.all(),
        "invoice": InvoiceReseller.objects.all(),
        "delivery_note": DeliveryNoteReseller.objects.all(),
        "gdpr.deletion_request": DeletionRequest.objects.all(),
    }


def _owned_records(subject: ErasureSubject) -> dict[str, Q]:
    """Which of the :func:`_linkable_records` are ``subject``'s, by kind."""
    user, member, reseller = subject.user, subject.member, subject.reseller
    owned: dict[str, Q] = {}
    request_owners: list[Q] = []
    if user is not None:
        owned["user"] = Q(pk=user.pk)
        request_owners.append(Q(user_id=user.pk))
    if member is not None:
        owned["member"] = Q(pk=member.pk)
        owned["subscription"] = Q(member_id=member.pk)
        request_owners.append(Q(member_id=member.pk))
    if reseller is not None:
        owned["reseller"] = Q(pk=reseller.pk)
        owned["invoice"] = Q(reseller_id=reseller.pk)
        owned["delivery_note"] = Q(order__reseller_id=reseller.pk)
        request_owners.append(Q(reseller_id=reseller.pk))
    if request_owners:
        owned["gdpr.deletion_request"] = reduce(or_, request_owners)
    return owned


def _rows_linked_to(record_type: str, records: QuerySet[Any]) -> Q:
    """The email-log rows linked to one of ``records``. The send paths write
    the record's pk as a string."""
    record_ids = records.annotate(record_id=Cast("pk", CharField())).values("record_id")
    return Q(related_object_type=record_type, related_object_id__in=record_ids)


def _login_addresses(subject: ErasureSubject) -> set[str]:
    """The login's address and the addresses its invitations went to."""
    user = subject.user
    if user is None:
        return set()
    invited = UserInvitation.objects.filter(user_id=user.pk).values_list(
        "email", flat=True
    )
    return {_normalized(address) for address in [user.email, *invited]} - {""}


def _record_addresses(subject: ErasureSubject) -> set[str]:
    """Every address on the subject's member and reseller records."""
    addresses: list[str | None] = []
    if subject.member is not None:
        member = subject.member
        addresses += [member.email, member.email_2, member.email_3]
    if subject.reseller is not None:
        contact = subject.reseller.contact
        addresses += [
            contact.email,
            contact.email_2,
            contact.email_3,
            contact.order_email,
            subject.reseller.invoice_email,
        ]
    return {_normalized(address) for address in addresses} - {""}


def _requested_addresses(owned: dict[str, Q]) -> set[str]:
    """The addresses the subject's deletion requests were filed under, which
    the outcome of a request is mailed to."""
    request_owners = owned.get("gdpr.deletion_request")
    if request_owners is None:
        return set()
    requested = DeletionRequest.objects.filter(request_owners).values_list(
        "requested_email", flat=True
    )
    return {_normalized(address) for address in requested} - {""}


def _held_elsewhere(
    addresses: set[str], subject: ErasureSubject, farm_addresses: AbstractSet[str]
) -> set[str]:
    """The ``addresses`` a record outside ``subject`` holds, or the farm."""
    if not addresses:
        return set()
    user, member, reseller = subject.user, subject.member, subject.reseller
    logins = get_user_model().objects.all()
    if user is not None:
        logins = logins.exclude(pk=user.pk)
    members = Member.objects.all()
    if member is not None:
        members = members.exclude(pk=member.pk)
    resellers = Reseller.objects.all()
    contacts = ContactEntity.objects.all()
    if reseller is not None:
        resellers = resellers.exclude(pk=reseller.pk)
        # A contact another reseller shares holds that reseller's addresses too.
        if not resellers.filter(contact_id=reseller.contact_id).exists():
            contacts = contacts.exclude(pk=reseller.contact_id)

    held = addresses & farm_addresses
    for records, fields in (
        (logins, ("email",)),
        (members, ("email", "email_2", "email_3")),
        (contacts, ("email", "email_2", "email_3", "order_email")),
        (resellers, ("invoice_email",)),
    ):
        held |= _held_in(records, fields, addresses)
    return held


def _held_in(
    records: QuerySet[Any], fields: tuple[str, ...], addresses: set[str]
) -> set[str]:
    """The ``addresses`` any of ``records`` holds in one of ``fields``,
    compared trimmed and lower-cased."""
    normalized = {f"normalized_{field}": Lower(Trim(field)) for field in fields}
    holds = reduce(or_, (Q(**{f"{name}__in": addresses}) for name in normalized))
    rows = records.annotate(**normalized).filter(holds).values_list(*normalized)
    return {value for row in rows for value in row} & addresses


def _farm_addresses() -> dict[str, RecipientCategory]:
    """The farm's own addresses: the accounting address of its mail settings,
    and its office and order mailboxes with the sender and reply-to addresses.
    An address that is both counts as the office's: accounting copies sent to
    the office mailbox reveal no other inbox."""
    tenants = tenants_with_schema(connection.schema_name)
    office: list[str | None] = []
    accounting: list[str | None] = []
    for row in tenants.values_list("email", "email_for_orders"):
        office += row
    mail_settings = TenantEmailConfig.objects.filter(tenant__in=tenants)
    for from_email, reply_to_email, accounting_email in mail_settings.values_list(
        "from_email", "reply_to_email", "accounting_email"
    ):
        office += [from_email, reply_to_email]
        accounting.append(accounting_email)
    categories = dict.fromkeys(
        map(_normalized, accounting), RecipientCategory.FARM_ACCOUNTING
    )
    categories.update(
        dict.fromkeys(map(_normalized, office), RecipientCategory.FARM_OFFICE)
    )
    categories.pop("", None)
    return categories
