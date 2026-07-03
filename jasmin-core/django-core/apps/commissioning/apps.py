from django.apps import AppConfig


class CommissioningConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.commissioning"
    verbose_name = "Commissioning App"

    def ready(self) -> None:
        # Register models with django-auditlog so every create/update/delete
        # is recorded with the acting user.
        from auditlog.registry import auditlog

        # By ``ready()`` time, ``apps.commissioning.models.__init__`` has
        # already imported every submodule — so one consolidated import
        # is safe (no circular-import risk) and keeps this list aligned
        # with the public model surface in ``models/__init__.py``.
        from .models import (
            ConsentDocument,
            ConsentRecord,
            ContactEntity,
            CoopShare,
            DeliveryNoteContent,
            DeliveryNoteReseller,
            InvoiceReseller,
            InvoiceResellerContent,
            Member,
            Order,
            OrderContent,
            PaymentCycle,
            Reseller,
            ShareDelivery,
            Subscription,
        )

        # Member: full audit, but mask IBAN and contact-detail fields so the
        # raw values never leak into the audit log itself.
        auditlog.register(
            Member,
            mask_fields=[
                "iban",
                "email",
                "email_2",
                "email_3",
                "address",
                "zip_code",
                "city",
                "account_owner",
                "note",
                # Free-text cancellation reason — routinely holds PII; mask so
                # the raw value never lands in the forever-retained audit diffs.
                "cancellation_reason",
                # Statutory date-of-birth (GenG §30): PII erased on deletion,
                # special-category-adjacent. Masked like iban/email so the raw
                # DoB never lands in the forever-retained auditlog change diffs.
                # (first_name/last_name stay unmasked as audit display values.)
                "birth_date",
            ],
        )
        # B2B counterparties. The contact carries the PII (name is an audit
        # display value; iban / email / phone / address are masked like
        # Member's). Registering both gives the reseller/contact change
        # history a GoBD/Art.17 trail — and is what makes the
        # ``_scrub_auditlog_entries`` Reseller/ContactEntity scrub on
        # anonymization act on real rows instead of an empty set.
        auditlog.register(
            ContactEntity,
            mask_fields=[
                "iban",
                "email",
                "email_2",
                "email_3",
                "order_email",
                "phone",
                "phone_2",
                "phone_3",
                "address",
                "zip_code",
                "city",
            ],
        )
        auditlog.register(
            Reseller,
            mask_fields=[
                "invoice_address",
                "invoice_plz",
                "invoice_city",
                "invoice_email",
                "note",
            ],
        )

        auditlog.register(CoopShare)
        auditlog.register(Subscription)
        auditlog.register(ShareDelivery)  # joker_taken changes etc.
        auditlog.register(PaymentCycle)

        # Commercial documents — the highest-priority audit targets.
        # ``document_hash`` is excluded because it's a deterministic
        # function of the other fields; logging both would just duplicate
        # noise on every mutation.
        auditlog.register(InvoiceReseller, exclude_fields=["document_hash"])
        auditlog.register(InvoiceResellerContent)
        auditlog.register(DeliveryNoteReseller)
        auditlog.register(DeliveryNoteContent)
        auditlog.register(Order)
        auditlog.register(OrderContent)

        # Consent versioning: ConsentRecord is the audit-relevant table.
        # ConsentDocument is append-only by convention; register it too
        # so any post-hoc body edit (which violates the convention) is
        # captured. ``body_sha256`` is excluded — it's derived from
        # ``body`` and would just duplicate the diff line.
        auditlog.register(ConsentDocument, exclude_fields=["body_sha256"])
        auditlog.register(ConsentRecord)
