from django.apps import AppConfig


class PaymentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.payments"
    verbose_name = "Payments"

    def ready(self) -> None:
        from auditlog.registry import auditlog

        from apps.shared.sepa_mandate_hooks import (
            set_sepa_mandate_revoked_handler,
        )
        from apps.shared.subscription_hooks import set_subscription_changed_handler

        from .constants import PaymentMethodOptions
        from .models import BillingProfile, BillingRun, ChargeSchedule
        from .services import ChargeScheduleService

        # Commissioning emits a subscription-changed signal (admin-confirm,
        # cancel, opt-in toggle) via apps.shared.subscription_hooks WITHOUT
        # importing payments — payments reacts here by re-planning the charge
        # schedule. Inverts the old commissioning -> payments import so the
        # one-way isolation holds. ``ChargeScheduleService`` is captured but
        # ``.regenerate_for_subscription`` is resolved at call time, so test
        # mocks on the class attribute are still honoured.
        def _on_subscription_changed(subscription) -> None:
            ChargeScheduleService.regenerate_for_subscription(subscription)

        set_subscription_changed_handler(_on_subscription_changed)

        # A member withdrawing SEPA-mandate consent (Art. 7(3)) must stop the
        # direct debit. Commissioning's ConsentService.revoke emits this via
        # apps.shared.sepa_mandate_hooks WITHOUT importing payments; we switch
        # the member's BillingProfile off SEPA to BANK_TRANSFER so no future run
        # auto-debits them (charges still plan; the office settles manually).
        def _on_sepa_mandate_revoked(member) -> None:
            profile = BillingProfile.objects.filter(
                member=member,
                payment_method=PaymentMethodOptions.SEPA_DIRECT_DEBIT,
            ).first()
            if profile is None:
                return
            profile.payment_method = PaymentMethodOptions.BANK_TRANSFER
            profile.save(update_fields=["payment_method"])

        set_sepa_mandate_revoked_handler(_on_sepa_mandate_revoked)

        # ``iban`` / ``account_holder`` are ``EncryptedCharField``
        # on the model (Fernet ciphertext at rest). Without ``mask_fields``,
        # auditlog stores the *decrypted* old/new plaintext in the diff
        # JSON, bypassing the encryption-at-rest design and writing PII
        # into ``auditlog_logentry``. ``sepa_mandate_reference`` isn't
        # encrypted at rest but is bank-mandate-identifier material that
        # doesn't belong in plaintext audit rows either. Same masking
        # bias as ``Member`` in commissioning/apps.py.
        auditlog.register(
            BillingProfile,
            mask_fields=[
                "iban",
                "account_holder",
                "sepa_mandate_reference",
            ],
        )
        auditlog.register(ChargeSchedule)
        auditlog.register(BillingRun)
