"""Subject Access Request (Art. 15) bundle builder."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.utils import timezone

from apps.accounts.models import JasminUser
from apps.commissioning.models import (
    ConsentRecord,
    ContactEntity,
    CoopShare,
    InvoiceReseller,
    Member,
    MemberLoan,
    Order,
    Reseller,
    Subscription,
    UserInvitation,
)
from apps.notifications.models import EmailLog
from apps.payments.models import BillingProfile, ChargeSchedule

from ..models import DeletionRequest
from .anonymization import _ci_recipient_q, _ci_username_q

if TYPE_CHECKING:
    # ``GDPRService`` is assembled in the package ``__init__`` and bound into
    # this module's namespace there. Method bodies must resolve it at call
    # time through the ASSEMBLED class so monkeypatched attributes on
    # ``GDPRService`` are honoured.
    from . import GDPRService


def _sar_contact_entity(contact: ContactEntity) -> dict:
    """Serialise a ContactEntity for the SAR bundle (Reseller's
    contact info). Kept at module level so ``GDPRService._sar_reseller``
    can stay focused on the Reseller row itself.

    Mirrors the ``apps.commissioning.models.basics.ContactEntity``
    column list field-for-field — when a new column lands on that
    model, add it here too so the SAR keeps reflecting the full
    row. The reverse ``user`` OneToOne is intentionally not
    surfaced: the data subject IS the user, so re-emitting their
    own id would be noise."""
    return {
        "contact_id": str(contact.pk),
        # Identity
        "company_name": contact.company_name,
        "first_name": contact.first_name,
        "last_name": contact.last_name,
        "acronym": contact.acronym,
        # Address + geocoded position
        "address": contact.address,
        "zip_code": contact.zip_code,
        "city": contact.city,
        "country": contact.country,
        # Native Decimal — serializer formats it to string.
        "coords_lon": contact.coords_lon,
        "coords_lat": contact.coords_lat,
        # Contact channels
        "email": contact.email,
        "email_2": contact.email_2,
        "email_3": contact.email_3,
        "order_email": contact.order_email,
        "phone": contact.phone,
        "phone_2": contact.phone_2,
        "phone_3": contact.phone_3,
        # Tax / banking identifiers
        "uid": contact.uid,
        # Encrypted at rest; surface decrypted so the export is
        # legible (the whole point of an Art-15 export).
        "iban": str(contact.iban) if contact.iban else None,
    }


class SubjectAccessMixin:
    """SAR bundle builder, mixed into
    :class:`apps.gdpr.services.GDPRService`."""

    # ---------------------------------------------------------------
    # Subject Access Request — Art. 15 (Step 7 of the roadmap)
    # ---------------------------------------------------------------
    #
    # ``get_subject_access_bundle`` is the single source of truth for
    # "everything we store about this user". A real SAR (data subject
    # mails us asking "what do you have on me?") is satisfiable from
    # the JSON returned by this method alone — no manual SQL needed.
    #
    # Each section is filled by a private ``_sar_<section>`` helper so
    # the orchestrator stays readable and individual sections can be
    # unit-tested in isolation. Sections that don't apply to the
    # caller's persona (e.g. ``reseller_orders`` for a member who is
    # not a B2B customer) return ``[]`` or ``None`` rather than being
    # omitted — keeps the schema stable for the frontend.
    #
    # FORMAT_VERSION is bumped whenever a section is added or its
    # shape changes incompatibly. The frontend can branch on it.
    # v2: added the ``billing_profile`` section (SEPA mandate).
    # v3: added the ``user_invitations`` section.

    SAR_FORMAT_VERSION = 3

    # Heavy categories (EmailLog, axes login records) can grow without
    # bound for a long-tenured user. The SAR endpoint is rate-limited
    # per-user (caller authenticates), but we still cap the lists so a
    # single GET doesn't have to serialise 10k rows. Caps are
    # generous; surface a ``_truncated_at`` marker so the user knows.
    SAR_EMAIL_LOG_LIMIT = 500
    SAR_LOGIN_HISTORY_LIMIT = 200

    @staticmethod
    def get_subject_access_bundle(user: JasminUser) -> dict:
        """Return every piece of personal data we hold for ``user`` —
        DSGVO Art. 15 right of access.

        Output is a plain dict of NATIVE Python types (``datetime``,
        ``date``, ``Decimal``, ``str``, ``None``). The
        :class:`apps.gdpr.serializers.SubjectAccessBundleSerializer`
        formats it for the HTTP response (ISO 8601 datetimes,
        Decimal → string, etc.). Keeping the service-side dict
        un-stringified means each ``_sar_<section>`` helper reads
        like a model→dict projection, and a future caller (e.g.
        the ZIP-export job in Step 7's roadmap follow-up) can
        reuse the same data without re-parsing.

        Top-level shape (all keys always present; lists empty
        rather than omitted so the frontend has a stable contract):

        - ``format_version`` (int) — bump on breaking changes.
        - ``exported_at`` (datetime) — server clock at export time.
        - ``subject`` — id + currently-displayed email of the requester.
        - ``account`` — JasminUser row fields.
        - ``member`` — Member row fields (None if no member profile).
        - ``reseller`` — Reseller + linked ContactEntity fields (None
          if the user isn't B2B).
        - ``consents`` — every ConsentRecord with the document
          version it was given against.
        - ``coop_shares`` — GenG cooperative-share holdings.
        - ``subscriptions`` — active + historical service contracts.
        - ``member_loans`` — loans the member extended to the co-op.
        - ``charge_schedules`` — billing rows (the member's ledger).
        - ``reseller_orders`` — B2B order history.
        - ``reseller_invoices`` — B2B invoice history.
        - ``email_log`` — emails sent to the user's known addresses
          (capped at ``SAR_EMAIL_LOG_LIMIT``).
        - ``login_history`` — successful + failed login records
          (capped at ``SAR_LOGIN_HISTORY_LIMIT``).
        - ``deletion_requests`` — Art. 17 requests the user has filed.
        - ``user_invitations`` — invitations the co-op sent to the user
          (the token is surfaced as presence only, never the raw value).

        Deliberately excluded (reasoned Art. 15 scope decisions):
        - django-auditlog change-history (``LogEntry.changes`` /
          ``object_repr``) for the subject's rows. Anonymization scrubs these
          on erasure, but the raw internal audit diffs are an operational
          record whose disclosure is a legal judgement call and can embed
          third-party data inside a single diff; the substantive PII they hold
          (old/new names, addresses, IBAN, consent IP/UA) is already surfaced
          by the live-value sections above. If a supervisory authority requires
          it, add a capped ``_sar_audit_history`` keyed off the member/reseller
          FK chains that ``_scrub_auditlog_entries`` already walks.
        """
        member = Member.objects.filter(user=user).first()
        reseller = Reseller.objects.filter(linked_user=user).first()
        # SAR side-channel (EmailLog + login history) must key ONLY on the
        # subject's UNIQUE addresses — a shared email_2/email_3 would pull in
        # another subject's records (Art. 15 forbids over-disclosing a third
        # party). Anonymization still scrubs every address (the default).
        known_emails = GDPRService._collect_known_emails(
            user, include_shared_secondaries=False
        )

        return {
            "format_version": GDPRService.SAR_FORMAT_VERSION,
            "exported_at": timezone.now(),
            "subject": {
                "user_id": str(user.pk),
                "email": user.email,
            },
            "account": GDPRService._sar_account(user),
            "member": GDPRService._sar_member(member),
            "billing_profile": GDPRService._sar_billing_profile(member),
            "reseller": GDPRService._sar_reseller(reseller),
            "consents": GDPRService._sar_consents(member),
            "coop_shares": GDPRService._sar_coop_shares(member),
            "subscriptions": GDPRService._sar_subscriptions(member),
            "member_loans": GDPRService._sar_member_loans(member),
            "charge_schedules": GDPRService._sar_charge_schedules(member),
            "reseller_orders": GDPRService._sar_reseller_orders(reseller),
            "reseller_invoices": GDPRService._sar_reseller_invoices(reseller),
            "email_log": GDPRService._sar_email_log(known_emails),
            "login_history": GDPRService._sar_login_history(known_emails),
            "deletion_requests": GDPRService._sar_deletion_requests(user),
            "user_invitations": GDPRService._sar_user_invitations(user),
        }

    # ---- SAR per-section helpers --------------------------------

    @staticmethod
    def _sar_account(user: JasminUser) -> dict:
        """Full ``JasminUser`` row — see
        :class:`apps.gdpr.serializers.AccountSerializer` for the
        field list (it's the audit). ``password`` is intentionally
        omitted (never expose, even hashed); ``groups`` /
        ``user_permissions`` are Django-auth internals with no SAR
        value."""
        return {
            "user_id": str(user.pk),
            "public_id": str(user.public_id),
            "username": user.username,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            # Avatar is an ImageField — surface the relative storage
            # path. ``str(user.avatar)`` returns "" for an empty
            # field; coerce to None for cleaner JSON.
            "avatar": str(user.avatar) if user.avatar else None,
            "account_status": user.account_status,
            "is_active": user.is_active,
            "is_superuser": user.is_superuser,
            "user_language": user.user_language,
            "sidebar_collapsed": user.sidebar_collapsed,
            "theme": user.theme,
            "edit_mode": user.edit_mode,
            "roles": list(user.roles or []),
            "date_joined": user.date_joined,
            "last_login": user.last_login,
            "last_login_ip": user.last_login_ip,
            "activated_at": user.activated_at,
            "inactivated_at": user.inactivated_at,
            "created_at": user.created_at,
            "updated_at": user.updated_at,
        }

    @staticmethod
    def _sar_member(member: Member | None) -> dict | None:
        """Full ``Member`` row + mixin fields. ``user`` FK skipped
        (the subject IS the user). See
        :class:`apps.gdpr.serializers.MemberSerializer` for the
        canonical field list."""
        if member is None:
            return None
        return {
            "member_id": str(member.pk),
            "member_number": member.member_number,
            # Identity
            "company_name": member.company_name,
            "first_name": member.first_name,
            "last_name": member.last_name,
            "pickup_name": member.pickup_name,
            # Address
            "address": member.address,
            "zip_code": member.zip_code,
            "city": member.city,
            "country": member.country,
            # Contact channels
            "email": member.email,
            "email_2": member.email_2,
            "email_3": member.email_3,
            # Banking (encrypted at rest, plaintext on read).
            "account_owner": member.account_owner,
            "iban": str(member.iban) if member.iban else None,
            "number_of_rates": member.number_of_rates,
            # Denormalised consent timestamps (verbatim model field
            # names; the model columns predate the ``_at`` naming
            # convention and the existing frontend reader keys off
            # the un-suffixed names). Full event log with consented
            # document version lives in ``consents`` below.
            "sepa_consent": member.sepa_consent,
            "withdrawal_consent": member.withdrawal_consent,
            "privacy_consent": member.privacy_consent,
            # State flags + dates
            "is_active": member.is_active,
            "is_trial": member.is_trial,
            "is_student": member.is_student,
            "entry_date": member.entry_date,
            "birth_date": member.birth_date,
            # CancellableMixin — Austrittsdatum per GenG §30
            "cancelled_at": member.cancelled_at,
            "cancelled_effective_at": member.cancelled_effective_at,
            # Free-text "why" of the exit — PII_IMMEDIATE (may hold health
            # reasons / complaints), so it belongs in the Art. 15 bundle.
            "cancellation_reason": member.cancellation_reason,
            "note": member.note,
            # AdminConfirmableMixin
            "admin_confirmed": member.admin_confirmed,
            "admin_confirmed_at": member.admin_confirmed_at,
            "admin_rejection_reason": member.admin_rejection_reason,
            # CreatedMixin
            "created_at": member.created_at,
            # WaitingListMixin
            "on_waiting_list": member.on_waiting_list,
            "waiting_list_status": member.waiting_list_status,
            "waiting_list_position": member.waiting_list_position,
            "notification_sent_at": member.notification_sent_at,
            "notification_expires_at": member.notification_expires_at,
            "response_received_at": member.response_received_at,
        }

    @staticmethod
    def _sar_billing_profile(member: Member | None) -> dict | None:
        """The member's SEPA Direct Debit mandate (``payments.BillingProfile``).

        Distinct from the ``member.iban`` copy in ``_sar_member`` — the mandate
        reference + signing/first-use dates live ONLY here and are classified
        PII_IMMEDIATE, so Art. 15 must surface them. IBAN + holder are encrypted
        at rest, decrypted to string on read like ``_sar_member``."""
        if member is None:
            return None
        profile = BillingProfile.objects.filter(member=member).first()
        if profile is None:
            return None
        return {
            "billing_profile_id": str(profile.pk),
            "payment_method": profile.payment_method,
            "is_active": profile.is_active,
            # Banking (encrypted at rest, plaintext on read).
            "account_holder": profile.account_holder or None,
            "iban": str(profile.iban) if profile.iban else None,
            # SEPA mandate — the standing direct-debit authorisation.
            "sepa_mandate_reference": profile.sepa_mandate_reference,
            "sepa_mandate_signed_at": profile.sepa_mandate_signed_at,
            "sepa_mandate_first_use_at": profile.sepa_mandate_first_use_at,
            "sepa_mandate_paper_received_at": profile.sepa_mandate_paper_received_at,
            "notes": profile.notes or None,
        }

    @staticmethod
    def _sar_reseller(reseller: Reseller | None) -> dict | None:
        """Mirrors the ``apps.commissioning.models.resellers.Reseller``
        column list field-for-field, plus the nested ContactEntity
        via ``_sar_contact_entity``. ``linked_user`` and the
        ``contact`` FK are NOT surfaced as raw ids — the data
        subject IS the linked user, and ``contact`` is expanded
        inline below. ``offer_group`` collapses to ``name`` for
        readability (the SAR is for a human; raw FK ids would be
        meaningless to the requester)."""
        if reseller is None:
            return None
        contact = reseller.contact
        offer_group = reseller.offer_group
        return {
            "reseller_id": str(reseller.pk),
            # Identifier fields the office uses to refer to this
            # reseller in spreadsheets and on invoices.
            "customer_number": reseller.customer_number,
            "filial_number": reseller.filial_number,
            "name_for_member_pages": reseller.name_for_member_pages,
            # Persona-type flags — "what KIND of relationship does
            # the co-op have with this Reseller row?". The
            # ``is_active_*`` mirrors are the operational on/off.
            "is_seller": reseller.is_seller,
            "is_reseller": reseller.is_reseller,
            "is_donation_recipient": reseller.is_donation_recipient,
            "is_supplier": reseller.is_supplier,
            "is_active_seller": reseller.is_active_seller,
            "is_active_reseller": reseller.is_active_reseller,
            "is_active_donation_recipient": reseller.is_active_donation_recipient,
            "is_active_supplier": reseller.is_active_supplier,
            # Per-document delivery channel preferences (does the
            # reseller want offers / orders / delivery notes /
            # invoices by email).
            "offer_via_email": reseller.offer_via_email,
            "order_via_email": reseller.order_via_email,
            "delivery_note_via_email": reseller.delivery_note_via_email,
            "invoice_via_email": reseller.invoice_via_email,
            # Pricing-tier grouping. Surface the group's NAME
            # rather than the raw FK id — names are stable enough
            # to be meaningful in a SAR, ids are not.
            "offer_group": offer_group.name if offer_group else None,
            # Invoice-display fields (what gets rendered on
            # printed invoices to this reseller).
            "invoice_name": reseller.invoice_name,
            "invoice_name2": reseller.invoice_name2,
            "invoice_address": reseller.invoice_address,
            "invoice_plz": reseller.invoice_plz,
            "invoice_city": reseller.invoice_city,
            "invoice_email": reseller.invoice_email,
            "note": reseller.note,
            # Nested contact block — full field-by-field mirror,
            # see ``_sar_contact_entity``.
            "contact": _sar_contact_entity(contact) if contact else None,
        }

    @staticmethod
    def _sar_consents(member: Member | None) -> list[dict]:
        """Every ``ConsentRecord`` ever stamped for this member —
        includes the document version they consented to + the
        forensic IP/UA capture + any later revocation. Ordered
        newest-first so the export reads like a changelog."""
        if member is None:
            return []
        records = (
            ConsentRecord.objects.filter(member=member)
            .select_related("document")
            .order_by("-consented_at")
        )
        return [
            {
                "id": str(record.pk),
                "kind": record.document.kind,
                "document_version": record.document.version,
                "document_locale": record.document.locale,
                "consented_at": record.consented_at,
                "ip_address": record.ip_address,
                "user_agent": record.user_agent,
                "revoked_at": record.revoked_at,
                "revoked_reason": record.revoked_reason,
            }
            for record in records
        ]

    @staticmethod
    def _sar_coop_shares(member: Member | None) -> list[dict]:
        if member is None:
            return []
        # CoopShare doesn't carry ``created_at`` (PayableMixin doesn't
        # mix in CreatedMixin); sort by pk as a stable proxy for
        # insertion order.
        rows = CoopShare.objects.filter(member=member).order_by("id")
        return [
            {
                "id": str(share.pk),
                "amount_of_coop_shares": share.amount_of_coop_shares,
                "is_increase": share.is_increase,
                "note": share.note,
                "cancellation_reason": share.cancellation_reason,
                # PayableMixin
                "due_date": share.due_date,
                "paid_at": share.paid_at,
                # AdminConfirmableMixin
                "admin_confirmed": share.admin_confirmed,
                "admin_confirmed_at": share.admin_confirmed_at,
                "admin_rejection_reason": share.admin_rejection_reason,
            }
            for share in rows
        ]

    @staticmethod
    def _sar_subscriptions(member: Member | None) -> list[dict]:
        if member is None:
            return []
        rows = (
            Subscription.objects.filter(member=member)
            .select_related("share_type_variation")
            .order_by("-valid_from")
        )
        return [
            {
                "id": str(sub.pk),
                # share-type-variation NAME (the part the member would
                # recognise from their dashboard). Raw FK ids are noise
                # in a SAR.
                "share_type_variation": str(sub.share_type_variation),
                "is_trial": sub.is_trial,
                "quantity": sub.quantity,
                "price_per_delivery": sub.price_per_delivery,
                "notice_period_duration": sub.notice_period_duration,
                # TimeBoundMixin
                "valid_from": sub.valid_from,
                "valid_until": sub.valid_until,
                # AdminConfirmableMixin
                "admin_confirmed": sub.admin_confirmed,
                "admin_confirmed_at": sub.admin_confirmed_at,
                "admin_rejection_reason": sub.admin_rejection_reason,
                # CreatedMixin
                "created_at": sub.created_at,
                # CancellableMixin
                "cancelled_at": sub.cancelled_at,
                "cancelled_effective_at": sub.cancelled_effective_at,
                "cancellation_reason": sub.cancellation_reason,
                # WaitingListMixin
                "on_waiting_list": sub.on_waiting_list,
                "waiting_list_status": sub.waiting_list_status,
                "waiting_list_position": sub.waiting_list_position,
            }
            for sub in rows
        ]

    @staticmethod
    def _sar_member_loans(member: Member | None) -> list[dict]:
        if member is None:
            return []
        rows = MemberLoan.objects.filter(member=member).order_by("-start_date")
        return [
            {
                "id": str(loan.pk),
                "amount": loan.amount,
                "interest_rate": loan.interest_rate,
                "start_date": loan.start_date,
                "end_date": loan.end_date,
                "paid_back_date": loan.paid_back_date,
                "cancelled_reason": loan.cancelled_reason,
                # AdminConfirmableMixin
                "admin_confirmed": loan.admin_confirmed,
                "admin_confirmed_at": loan.admin_confirmed_at,
                "admin_rejection_reason": loan.admin_rejection_reason,
                # CreatedMixin
                "created_at": loan.created_at,
            }
            for loan in rows
        ]

    @staticmethod
    def _sar_charge_schedules(member: Member | None) -> list[dict]:
        if member is None:
            return []
        rows = ChargeSchedule.objects.filter(member=member).order_by("-period_start")
        return [
            {
                "id": str(charge.pk),
                "period_start": charge.period_start,
                "period_end": charge.period_end,
                "due_date": charge.due_date,
                "expected_amount": charge.expected_amount,
                "currency": charge.currency,
                "description": charge.description,
                "status": charge.status,
                "end_to_end_id": charge.end_to_end_id,
            }
            for charge in rows
        ]

    @staticmethod
    def _sar_reseller_orders(reseller: Reseller | None) -> list[dict]:
        """B2B order HEADERS. Line items (``OrderContent``) are intentionally
        NOT nested (deliberate scope): they are low-value transactional detail
        whose per-order volume can be large, and the itemised substance is
        already retrievable via the rendered order/invoice document surfaced on
        the row. Header + document is a complete Art. 15 disclosure. If itemised
        JSON is later required, nest a capped ``contents`` list here."""
        if reseller is None:
            return []
        rows = Order.objects.filter(reseller=reseller).order_by(
            "-year", "-delivery_week"
        )
        return [
            {
                "id": str(order.pk),
                "display_number": order.display_number,
                "year": order.year,
                "delivery_week": order.delivery_week,
                # Day-of-week numbers for the delivery / harvesting
                # / packing / washing / cleaning workflow steps.
                "day_number": order.day_number,
                "last_possible_ordering_day": order.last_possible_ordering_day,
                "harvesting_day": order.harvesting_day,
                "packing_day": order.packing_day,
                "washing_day": order.washing_day,
                "cleaning_day": order.cleaning_day,
                "is_donation": order.is_donation,
                "note": order.note,
                # FinalizableMixin
                "is_finalized": order.is_finalized,
                "finalized_at": order.finalized_at,
                # CreatedMixin
                "created_at": order.created_at,
            }
            for order in rows
        ]

    @staticmethod
    def _sar_reseller_invoices(reseller: Reseller | None) -> list[dict]:
        """B2B invoice HEADERS. Line items (``InvoiceResellerContent``) are
        intentionally NOT nested (deliberate scope): the itemised article /
        quantity / price detail is already disclosed by the rendered invoice
        document surfaced on the row (``file`` / ``xml_file``), and inlining
        every line for a high-volume reseller would bloat the JSON. Header +
        document is a complete Art. 15 disclosure. If itemised JSON is later
        required, nest a capped ``contents`` list here."""
        if reseller is None:
            return []
        rows = InvoiceReseller.objects.filter(reseller=reseller).order_by(
            "-date", "-pk"
        )
        return [
            {
                "id": str(invoice.pk),
                "display_number": invoice.display_number,
                "document_type": invoice.document_type,
                "document_hash": invoice.document_hash,
                "correction_reason": invoice.correction_reason,
                "items_are_grouped": invoice.items_are_grouped,
                "note": invoice.note,
                # Cross-references collapsed to display numbers (a
                # SAR for a human; raw FK ids would be noise).
                "cancels_invoice": (
                    invoice.cancels_invoice.display_number
                    if invoice.cancels_invoice
                    else None
                ),
                "cancelled_by_invoice": (
                    invoice.cancelled_by_invoice.display_number
                    if invoice.cancelled_by_invoice
                    else None
                ),
                # File pointers (relative storage paths).
                "file": str(invoice.file) if invoice.file else None,
                "xml_file": str(invoice.xml_file) if invoice.xml_file else None,
                # Dispatch state. The booleans are now derived
                # @properties on the model (True iff matching
                # ``*_at`` timestamp is set); kept in the SAR export
                # for human-readability of the JSON.
                "has_been_sent_to_reseller": invoice.has_been_sent_to_reseller,
                "has_been_sent_to_reseller_at": invoice.has_been_sent_to_reseller_at,
                "has_been_sent_to_accounting": invoice.has_been_sent_to_accounting,
                "has_been_sent_to_accounting_at": (
                    invoice.has_been_sent_to_accounting_at
                ),
                # DateDocumentMixin
                "date": invoice.date,
                # PayableMixin
                "due_date": invoice.due_date,
                "paid_at": invoice.paid_at,
                "has_been_paid": invoice.has_been_paid,
                # FinalizableMixin
                "is_finalized": invoice.is_finalized,
                "finalized_at": invoice.finalized_at,
            }
            for invoice in rows
        ]

    @staticmethod
    def _sar_email_log(known_emails: set[str]) -> dict:
        """Every EmailLog row sent to any of the user's addresses,
        newest first. Capped at ``SAR_EMAIL_LOG_LIMIT``; the dict
        carries ``truncated`` + ``total_count`` so the user knows
        when not all rows were returned (heavy-tenure case)."""
        if not known_emails:
            return {"truncated": False, "total_count": 0, "entries": []}
        qs = EmailLog.objects.filter(_ci_recipient_q(known_emails)).order_by(
            "-created_at"
        )
        total = qs.count()
        limit = GDPRService.SAR_EMAIL_LOG_LIMIT
        return {
            "truncated": total > limit,
            "total_count": total,
            "entries": [
                {
                    "id": str(row.pk),
                    "recipient": row.recipient,
                    "subject": row.subject,
                    "template": row.template,
                    "purpose": row.purpose,
                    "status": row.status,
                    "provider_message_id": row.provider_message_id,
                    "error": row.error,
                    "created_at": row.created_at,
                    "sent_at": row.sent_at,
                    "delivered_at": row.delivered_at,
                }
                for row in qs[:limit]
            ],
        }

    @staticmethod
    def _sar_login_history(known_emails: set[str]) -> dict:
        """``django-axes`` AccessLog (successful logins) +
        AccessFailureLog (failed attempts) keyed by username — which
        is the user's email. Useful for the data subject to spot
        unauthorised access attempts on their account."""
        if not known_emails:
            return {
                "truncated": False,
                "successful_logins": [],
                "failed_attempts": [],
            }
        # Local import: axes lives in TENANT_APPS.
        from axes.models import AccessFailureLog, AccessLog

        limit = GDPRService.SAR_LOGIN_HISTORY_LIMIT
        username_q = _ci_username_q(known_emails)
        successful_qs = AccessLog.objects.filter(username_q).order_by("-attempt_time")
        failed_qs = AccessFailureLog.objects.filter(username_q).order_by(
            "-attempt_time"
        )
        total_successful = successful_qs.count()
        total_failed = failed_qs.count()
        return {
            "truncated": (total_successful > limit or total_failed > limit),
            "successful_logins": [
                {
                    "username": row.username,
                    "ip_address": row.ip_address,
                    "user_agent": row.user_agent,
                    "attempt_time": row.attempt_time,
                    "logout_time": row.logout_time,
                }
                for row in successful_qs[:limit]
            ],
            "failed_attempts": [
                {
                    "username": row.username,
                    "ip_address": row.ip_address,
                    "user_agent": row.user_agent,
                    "attempt_time": row.attempt_time,
                    "locked_out": row.locked_out,
                }
                for row in failed_qs[:limit]
            ],
        }

    @staticmethod
    def _sar_deletion_requests(user: JasminUser) -> list[dict]:
        """The user's own Art. 17 history — every deletion request
        they've ever filed, including superseded / rejected / expired
        ones. Lets the user audit their own actions."""
        rows = DeletionRequest.objects.filter(user=user).order_by("-requested_at")
        return [
            {
                "id": str(request.pk),
                "requested_at": request.requested_at,
                "requested_email": request.requested_email,
                "state": str(request.state),
                "requires_admin_approval": request.requires_admin_approval,
                "email_confirmed_at": request.email_confirmed_at,
                # AdminConfirmableMixin (admin-approval branch)
                "admin_confirmed": request.admin_confirmed,
                "admin_confirmed_at": request.admin_confirmed_at,
                "admin_rejection_reason": request.admin_rejection_reason,
                "executed_at": request.executed_at,
            }
            for request in rows
        ]

    @staticmethod
    def _sar_user_invitations(user: JasminUser) -> list[dict]:
        """Invitations the co-op sent to this user's email. ``email`` is
        classified PII_IMMEDIATE and anonymization scrubs these rows
        (``_anonymize_user_invitations``), so Art. 15 must disclose them. The
        raw ``token`` is a live account-provisioning capability — surface only
        its PRESENCE, never the value."""
        rows = UserInvitation.objects.filter(user=user).order_by("-created_at")
        return [
            {
                "id": str(invitation.pk),
                "email": invitation.email,
                "status": invitation.status,
                "created_at": invitation.created_at,
                "expires_at": invitation.expires_at,
                "has_token": bool(invitation.token),
            }
            for invitation in rows
        ]
