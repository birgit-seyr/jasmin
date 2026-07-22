from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator, MaxValueValidator, MinValueValidator
from django.db import IntegrityError, models
from django.db.models import F, Q
from django.utils import timezone
from django_tenants.models import DomainMixin, TenantMixin
from encrypted_model_fields.fields import EncryptedCharField
from nanoid import generate

from apps.shared.iban_validator import validate_iban

ID_LENGTH = 12  # this is the ID in the JasminModel

# Use URL-safe alphabet (excludes similar-looking characters, excludes "_", this is needed for composite IDs!)
JASMIN_ID_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"


def generate_jasmin_id() -> str:
    return generate(alphabet=JASMIN_ID_ALPHABET, size=ID_LENGTH)


class JasminModel(models.Model):
    id = models.CharField(
        "ID",
        max_length=ID_LENGTH,
        unique=True,
        primary_key=True,
        default=generate_jasmin_id,
        editable=False,
    )

    class Meta:
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Save with retry logic for primary-key (nanoid) collision.

        Detects PK collisions specifically by inspecting the failing
        constraint, instead of substring-matching on the error message
        (which previously could swallow other unique-constraint failures
        that happened to mention the word "id").
        """
        max_retries = 5
        for attempt in range(max_retries):
            try:
                super().save(*args, **kwargs)
                return
            except IntegrityError as e:
                if self._is_pk_collision(e) and attempt < max_retries - 1:
                    self.id = generate_jasmin_id()
                else:
                    raise

    def _is_pk_collision(self, exc: IntegrityError) -> bool:
        """Return True iff the IntegrityError is a duplicate on the PK.

        Uses the psycopg constraint name when available
        (PostgreSQL convention: ``<table>_pkey``) and falls back to a
        narrower string match.
        """
        cause = getattr(exc, "__cause__", None)
        constraint_name = getattr(getattr(cause, "diag", None), "constraint_name", None)
        if constraint_name:
            return constraint_name.endswith("_pkey")
        # Fallback for non-PG backends or when diag is unavailable.
        msg = str(exc).lower()
        return "_pkey" in msg

    def get_display_id(self) -> str:
        """
        Convert the nanoid to a human-readable format.
        Examples:
            'aBc123XyZ' -> 'ABC-123-XYZ'
            'xK9mP2nQ4' -> 'XK9-MP2-NQ4'
        """
        if not self.id:
            return ""

        # Convert to uppercase for better readability
        readable_id = self.id.upper()

        # Split into groups of 3 characters with dashes
        CHUNK_SIZE = 3
        chunks = [
            readable_id[i : i + CHUNK_SIZE]
            for i in range(0, len(readable_id), CHUNK_SIZE)
        ]

        return "-".join(chunks)


class Tenant(TenantMixin, JasminModel):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, null=True)
    address = models.CharField(max_length=200, blank=True, null=True)
    zip_code = models.CharField(max_length=10, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    country = models.CharField(max_length=100, blank=True, null=True)
    organic_control_number = models.CharField(max_length=100, blank=True, null=True)
    tenant_language = models.CharField(max_length=8, blank=True, default="en")
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    email_for_orders = models.EmailField(blank=True, null=True)
    website = models.URLField(blank=True, null=True)

    # Art. 30 GDPR record-of-processing (VVT) controller-identity fields.
    # Populated by the office (ConfigurationGDPR) and read into the structured
    # ``gdpr_processing_activities`` export; empty until the tenant fills them.
    legal_form = models.CharField(max_length=100, blank=True, default="")
    data_protection_contact = models.CharField(max_length=200, blank=True, default="")
    dpo = models.CharField(max_length=200, blank=True, default="")
    supervisory_authority = models.CharField(max_length=200, blank=True, default="")

    # ---- Public legal-notice ("Impressum") fields ----
    # Rendered by the public ``PublicLegalNotice.tsx`` page (§ 5 DDG /
    # § 18 Abs. 2 MStV). All optional — each section on the page hides
    # when its field is blank, so an e.V. / GmbH / eG all render cleanly
    # from the same markup. Distinct from the GDPR ``supervisory_authority``
    # above, which is the *data-protection* authority, not the trade one.
    #
    # Register identity kept as three free-text fields (not an enum) because
    # tenants span Genossenschafts-/Vereins-/Handelsregister and possibly the
    # Austrian Firmenbuch — an enum would fight that variety immediately.
    register_type = models.CharField(max_length=100, blank=True, default="")
    register_number = models.CharField(max_length=50, blank=True, default="")
    register_court = models.CharField(max_length=200, blank=True, default="")
    # Vertretungsberechtigte (Vorstand / Geschäftsführer) and, for a
    # cooperative, the supervisory board — comma-separated names.
    legal_representatives = models.CharField(max_length=500, blank=True, default="")
    supervisory_board = models.CharField(max_length=500, blank=True, default="")
    # Redaktionell Verantwortlicher (§ 18 Abs. 2 MStV): name only; rendered
    # over the tenant's own postal address on the page.
    content_responsible = models.CharField(max_length=200, blank=True, default="")
    # § 36 VSBG dispute-resolution statement — a boolean toggling between the
    # two boilerplate variants (willing / not willing), which live in i18n so
    # the office never hand-writes legal text.
    participates_in_dispute_resolution = models.BooleanField(default=False)
    # eG-specific blocks (§ 54 GenG audit association + the accident-insurance
    # / professional association). Multiline so the full postal block fits;
    # the page hides the section when blank.
    auditing_association = models.TextField(blank=True, default="")
    professional_association = models.TextField(blank=True, default="")
    # Catch-all for the rare "wenn zutreffend" cases (Kammer / reglementierter
    # Beruf, licensing Aufsichtsbehörde, "in Abwicklung" notices) that don't
    # warrant a dedicated column. Rich text, same editor + sanitization path
    # as ``privacy_policy_html``.
    legal_notice_extra_html = models.TextField(blank=True, default="")

    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Localization / formatting (formerly under ``static_settings``)
    currency = models.CharField(max_length=8, default="EUR")
    timezone = models.CharField(
        max_length=64,
        default="UTC",
        help_text=(
            "Frontend display only. The Django backend uses the process-level "
            "``TIME_ZONE`` (settings.py) for every ``timezone.localdate()`` / "
            "``timezone.now()`` call — it does NOT switch per tenant. Onboarding "
            "a tenant in a different zone would silently get the server's "
            "concept of 'today' for backend business logic. If multi-region "
            "tenants ever become a real product requirement, every "
            "``timezone.localdate()`` callsite needs to flow through this field."
        ),
    )
    date_format = models.CharField(max_length=32, default="DD.MM.YYYY")
    time_format = models.CharField(max_length=16, default="HH:mm")
    csv_format = models.CharField(max_length=8, default="de")
    # BCP-47 locale tag used by Intl.NumberFormat on the frontend to format
    # decimals + thousand groups (e.g. "de-DE" → "1.234,50", "en-US" →
    # "1,234.50"). Tax/price math stays canonical (".") on the wire.
    number_locale = models.CharField(max_length=16, default="de-DE")

    # Feature-flag groups kept as JSON because they're variable-shape.
    navigation = models.JSONField(default=dict, blank=True)
    ai = models.JSONField(default=dict, blank=True)
    allow_upload_for_data_lists = models.BooleanField(default=True)

    logo = models.ImageField(upload_to="logos/", blank=True, null=True)
    bio_logo = models.ImageField(upload_to="bio_logos/", blank=True, null=True)

    fiscal_year_start_month = models.PositiveSmallIntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(12)],
    )
    iban = models.CharField(
        max_length=34,
        blank=True,
        null=True,
        validators=[validate_iban],
    )

    uid = models.CharField(max_length=20, blank=True, null=True)

    days_until_payment_due = models.IntegerField(default=14)

    # ---- SEPA creditor identity (issued once to the organization) ----
    # The dynamic billing settings (strategy, due day, joker handling) live
    # on TenantSettings so they can change over time.
    sepa_creditor_id = models.CharField(max_length=35, blank=True, default="")
    sepa_creditor_name = models.CharField(max_length=70, blank=True, default="")
    # BIC of the creditor's bank. Required by the ``sepaxml`` library
    # at config-construction time even though pain.008.001.02 marks
    # the corresponding XML element as optional — the library is
    # being more conservative than the spec. The bank tells the
    # office this 8/11-char code when they set up SEPA Direct Debit.
    sepa_creditor_bic = models.CharField(max_length=11, blank=True, default="")

    # ---- SEPA remittance text (what members see on their bank statement) ----
    # Rendered into the pain.008 ``Ustrd`` at export. Office-configurable
    # template with placeholders: ``{creditor}``, ``{member}``, ``{month}``,
    # ``{period}``, ``{amount}``. Blank → a friendly default
    # ("{creditor} - {month}"). ISO 20022 caps ``Ustrd`` at 140 chars.
    sepa_remittance_template = models.CharField(max_length=140, blank=True, default="")

    # ---- Privacy policy text (GDPR Art. 13/14 information duties) ----
    # Per-tenant override for the static ``PrivacyPolicyPage.tsx``
    # template. When blank, the frontend falls back to the shipped
    # default + the [placeholder] markers for org name / address /
    # email / phone. When set, this HTML replaces the body of the
    # privacy-policy route entirely. Stored as HTML to support the
    # rich-text editor on ``ConfigurationGeneral.tsx``.
    privacy_policy_html = models.TextField(blank=True, default="")

    # ---- Platform-owned action rate-limit overrides ----
    # Per-tenant overrides for the safe baseline caps in
    # ``apps.shared.tenants.rate_limits.DEFAULT_ACTION_RATE_LIMITS``. Shape:
    # ``{"<action>": {"weekly": int, "per_minute": int}}`` (partial keys allowed
    # — a missing action or bound falls back to the code default).
    #
    # This lives on the PUBLIC-schema ``Tenant`` row ON PURPOSE: it is editable
    # only through the super-admin platform, never from tenant/office settings.
    # The rate cap defends against a compromised *office* account generating a
    # flood of legally-relevant records — so the control that decides the ceiling
    # must sit one trust tier above that account. If it lived in tenant-editable
    # ``TenantSettings``, the attacker could simply raise their own cap first.
    #
    # ``editable=False`` is a belt-and-braces backstop: it keeps the field out of
    # any ``ModelSerializer(fields="__all__")`` (e.g. the tenant-facing
    # ``TenantSerializer``) by construction, so it can never be raised via a
    # tenant PATCH. Super-admin writes go through explicit ORM / serializer code,
    # which ``editable=False`` does not block.
    action_rate_limit_overrides = models.JSONField(
        default=dict, blank=True, editable=False
    )

    auto_create_schema = True
    auto_drop_schema = True

    def __str__(self) -> str:
        return self.name


class Domain(DomainMixin):
    pass


class RateLimitedAction(models.TextChoices):
    """The consequential verbs guarded by a per-tenant volume cap.

    Each value is a stable string stored in ``ActionRateLog.action`` and keyed
    in ``DEFAULT_ACTION_RATE_LIMITS`` — treat them as part of the config
    contract (renaming one silently drops its history + override).
    """

    INVOICE_FINALIZATION = "invoice_finalization", "Invoice finalization"
    DELIVERY_NOTE_FINALIZATION = (
        "delivery_note_finalization",
        "Delivery-note finalization",
    )
    SEPA_CHARGE_GENERATION = "sepa_charge_generation", "SEPA charge generation"
    MEMBER_CREATION = "member_creation", "Member creation"
    USER_CREATION = "user_creation", "User creation"
    SUBSCRIPTION_CONFIRMATION = (
        "subscription_confirmation",
        "Subscription confirmation",
    )


class ActionRateLog(JasminModel):
    """Append-only ledger of rate-limited actions — one row per event.

    Durable on PURPOSE: the cap protects legally-relevant volume, so it must
    survive a Redis flush (a cache-backed counter would not). Doubles as a
    forensic trail of who did what and when. Lives in the public schema (the
    ``shared.tenants`` app is a SHARED_APP).

    The tenant is identified by its ``schema_name`` string, NOT a FK to
    ``Tenant``. A public-schema FK to ``Tenant`` would add a commit-time
    constraint that a schema-only ``FakeTenant`` (background ``schema_context``
    work) and pytest ``transaction=True`` flushes can't satisfy — and the
    ledger needs no referential integrity, only a stable tenant key for
    counting. ``actor_id`` is a plain string (the actor is a tenant-schema
    ``JasminUser``; no cross-schema FK is possible). Pruned by
    ``prune_old_action_rate_log`` in ``tasks.py``.
    """

    # Tenant.schema_name (a Postgres identifier, ≤63 chars).
    tenant_schema = models.CharField(max_length=63)
    action = models.CharField(max_length=40, choices=RateLimitedAction.choices)
    # JasminUser id (tenant-schema STR pk) or "" when the actor is unknown
    # (e.g. a background billing run). Not an FK — cross-schema is impossible.
    actor_id = models.CharField(max_length=ID_LENGTH, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            # Serves the guard's count query: (tenant_schema, action, created_at >= t).
            models.Index(
                fields=["tenant_schema", "action", "created_at"],
                name="actionratelog_lookup_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.tenant_schema}:{self.action}@{self.created_at:%Y-%m-%d %H:%M:%S}"


class PackingMode(models.TextChoices):
    """How members receive their shares.

    BOXES   - all shares pre-packed into boxes (per delivery station).
    BULK    - members pick from bulk crates at the station (no per-box packing).
    MIXED   - hybrid: some share_type_variations are pre-packed,
              others are bulk. The per-variation
              ``ShareTypeVariation.is_packed_bulk`` flag selects which.
    """

    BOXES = "BOXES", "Boxes (pre-packed per station)"
    BULK = "BULK", "Bulk (members pick from crates)"
    MIXED = "MIXED", "Mixed (per share-type variation)"


class TenantSettings(JasminModel):
    # versioned settings for tenants with historical tracking, because these settings can change over time

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="tenant_settings"
    )
    valid_from = models.DateTimeField()
    valid_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # Cooperative shares
    has_coop_shares = models.BooleanField(default=True)  # done
    coop_shares_payment_after_admin_confirmation_in_days = models.IntegerField(
        default=14
    )
    # Whole-currency value of one cooperative share (matches CoopShare.
    # value_one_coop_share, also a PositiveIntegerField) — shares are sold in
    # whole units, so no sub-unit precision is needed.
    value_one_coop_share = models.PositiveIntegerField(default=100)
    min_number_coop_shares = models.PositiveIntegerField(default=3)
    max_number_coop_shares = models.PositiveIntegerField(default=100)
    # After a member is cancelled, their cooperative shares stay in the
    # Genossenschaft for this many months before they are due to be paid back
    # (the share's ``payback_due_date`` is snapshotted at cancellation =
    # cancelled_effective_at + this). 0 = due immediately on exit.
    retention_period_cancelled_members_coop_shares_in_months = (
        models.PositiveIntegerField(default=0)
    )
    uses_member_loans = models.BooleanField(default=False)

    # Season and timing
    # ``season_start_week`` is the ISO calendar week (1–53) the
    # seasonal cycle opens on. Stored as a week number (NOT a date)
    # so the same value drives ``valid_until`` derivations year over
    # year — a literal date would have to be rolled forward by the
    # office every January. ``null`` means the tenant hasn't
    # configured a seasonal cycle; consumers fall back to other
    # end-rules (one-year, manual).
    season_start_week = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(53)],
    )
    min_weeks_from_creation_to_start_delivery = models.PositiveIntegerField(default=2)

    # On-off (per-delivery opt-in) feature gate. Tenant-wide kill
    # switch for the ``ShareTypeVariation.requires_optin`` mechanism:
    # office UI hides the three opt-in configuration fields on the
    # variation modal when this is False, and the
    # ``ShareTypeVariationViewSet`` refuses to persist
    # ``requires_optin=True`` when it's off. Existing on-off
    # variations stay configured on the model but behave as plain
    # variations (no per-delivery toggle, no opt-in card on
    # MemberDetail).
    allows_share_type_variation_optin = models.BooleanField(default=False)

    # Trial subscriptions — gates short-term, non-committal subscription
    # offerings. Despite the historical "trial_shares" naming, these
    # control trial *subscriptions*, not Share/CoopShare equity.
    #
    # Decision tree (TrialPolicy):
    #   allows_trial_subscriptions?
    #     ├── No  → no trial subs anywhere
    #     └── Yes → allows_trial_subscriptions_for_trial_members?
    #               ├── Yes → trial members + full members can hold them
    #               └── No  → only full members (is_trial=False)
    allows_trial_subscriptions = models.BooleanField(default=True)
    allowed_trial_subscription_duration = models.PositiveIntegerField(
        default=4
    )  # in count of deliveries
    allows_trial_subscriptions_for_trial_members = models.BooleanField(default=True)
    info_sentence_about_trial_subscriptions = models.TextField(blank=True, null=True)

    # Waiting list — gates the whole waiting-list flow (offers, putting members/
    # subscriptions on a waiting list, waiting-list UI). When False the tenant
    # has no waiting list: at-capacity share types simply can't be subscribed to.
    allows_waiting_list_for_subscriptions = models.BooleanField(default=True)
    # How long a capacity reservation is held before it expires (days).
    reservation_ttl_days = models.PositiveIntegerField(default=14)

    # Jokers system
    uses_jokers = models.BooleanField(default=True)  # done
    default_amount_of_jokers = models.PositiveIntegerField(default=4)
    uses_jokers_for_trial_subscriptions = models.BooleanField(default=False)
    uses_donation_jokers = models.BooleanField(default=False)
    default_amount_of_additional_donation_jokers = models.PositiveIntegerField(
        default=3
    )

    packing_mode = models.CharField(
        max_length=10,
        choices=PackingMode.choices,
        default=PackingMode.BOXES,
    )
    percentage_added_to_bulk_packing_list = models.PositiveSmallIntegerField(
        blank=True, null=True
    )
    number_packing_stations = models.PositiveIntegerField(default=1)

    allows_solidarity_pricing = models.BooleanField(default=False)

    # layout app
    show_size_column = models.BooleanField(default=True)
    # When True, the harvest-share content planner auto-prefills each physical
    # variation's EMPTY day cells with the forecast amount split across sizes by
    # ``average_weight`` and weighted by the physical-variation counts (floored
    # to 0.10). Opt-in per tenant; default False leaves planning unchanged.
    distribute_forecast_by_weight = models.BooleanField(default=False)
    show_summary_in_harvest_share_planning_on_top = models.BooleanField(default=True)

    show_seller_name_of_share_article_in_share_for_member_on_page = models.BooleanField(
        default=True
    )
    round_up_to_full_pu_harvesting = models.BooleanField(default=False)

    # Public self-service registration on the login page. OFF hides the
    # register buttons AND makes /api/register/* refuse (defense-in-depth, not
    # only UI). Default False: member onboarding is manual unless a tenant
    # explicitly opts in.
    allows_self_registration = models.BooleanField(default=False)

    # Sales channels
    has_markets = models.BooleanField(default=False)
    sells_to_resellers = models.BooleanField(default=True)  # done

    # reseller invoice & deliver note settings
    payment_terms_reseller_in_days = models.PositiveIntegerField(default=14)  # done
    # Tenant-level Skonto defaults (per-reseller override on
    # ``Reseller.early_payment_discount_*``). NULL on both = no Skonto
    # offered by default; the PDF / ZUGFeRD generators only emit the
    # discount line when both fields are set.
    early_payment_discount_percent = models.DecimalField(
        max_digits=5, decimal_places=2, blank=True, null=True
    )
    early_payment_discount_days = models.PositiveIntegerField(blank=True, null=True)
    order_numbers_start_new_at_year_change = models.BooleanField(default=False)  # done
    order_number_prefix = models.CharField(max_length=10, default="BE")  # done
    delivery_note_numbers_start_new_at_year_change = models.BooleanField(
        default=False
    )  # done
    delivery_note_number_prefix = models.CharField(max_length=10, default="LS")  # done
    invoice_numbers_start_new_at_year_change = models.BooleanField(
        default=False
    )  # done
    invoice_number_prefix = models.CharField(max_length=10, default="RE")  # done
    correction_invoice_number_prefix = models.CharField(
        max_length=10, default="RK"
    )  # done
    left_column_footer_documents_reseller = models.TextField(
        blank=True, null=True
    )  # done
    middle_column_footer_documents_reseller = models.TextField(
        blank=True, null=True
    )  # done
    right_column_footer_documents_reseller = models.TextField(
        blank=True, null=True
    )  # done
    entry_line_1_invoice_reseller = models.TextField(blank=True, null=True)  # done
    entry_line_2_invoice_reseller = models.TextField(blank=True, null=True)  # done
    entry_line_3_invoice_reseller = models.TextField(blank=True, null=True)  # done
    greeting_line_1_invoice_reseller = models.TextField(blank=True, null=True)  # done
    greeting_line_2_invoice_reseller = models.TextField(blank=True, null=True)  # done
    greeting_line_3_invoice_reseller = models.TextField(blank=True, null=True)  # done
    entry_line_1_delivery_note_reseller = models.TextField(
        blank=True, null=True
    )  # done
    entry_line_2_delivery_note_reseller = models.TextField(
        blank=True, null=True
    )  # done
    entry_line_3_delivery_note_reseller = models.TextField(
        blank=True, null=True
    )  # done
    greeting_line_1_delivery_note_reseller = models.TextField(
        blank=True, null=True
    )  # done
    greeting_line_2_delivery_note_reseller = models.TextField(
        blank=True, null=True
    )  # done
    greeting_line_3_delivery_note_reseller = models.TextField(
        blank=True, null=True
    )  # done

    # Offer document
    entry_line_1_offer_reseller = models.TextField(blank=True, null=True)  # done
    entry_line_2_offer_reseller = models.TextField(blank=True, null=True)  # done
    entry_line_3_offer_reseller = models.TextField(blank=True, null=True)  # done
    greeting_line_1_offer_reseller = models.TextField(blank=True, null=True)  # done
    greeting_line_2_offer_reseller = models.TextField(blank=True, null=True)  # done
    greeting_line_3_offer_reseller = models.TextField(blank=True, null=True)  # done
    order_instructions_offer_reseller = models.TextField(blank=True, null=True)

    # Offer groups
    used_tiers_for_offers = models.JSONField(default=list, blank=True, null=True)
    offer_prices_are_per_pu = models.BooleanField(default=False)
    use_personalized_offers = models.BooleanField(default=True)

    # Subscription management
    subscriptions_end_at_end_of_season = models.BooleanField(default=False)
    subscriptions_end_after_one_year = models.BooleanField(default=True)
    subscriptions_are_auto_renewed = models.BooleanField(default=False)
    min_weeks_to_cancel_before_ending = models.PositiveIntegerField(default=6)

    # Subscription changes
    allows_share_type_variation_change = models.BooleanField(default=False)
    max_share_type_variation_changes = models.PositiveIntegerField(default=1)
    allows_delivery_station_change = models.BooleanField(default=False)
    max_delivery_station_changes = models.PositiveIntegerField(default=1)

    default_planning_granularity = models.CharField(
        max_length=10,
        choices=[("basic", "Basic"), ("tours", "Tours"), ("stations", "Stations")],
        default="basic",
    )
    uses_pledge_round = models.BooleanField(default=False)

    # When True the tenant uploads weekly share-amount totals via CSV
    # (``ExternalShareDemand``) instead of having Jasmin derive them from
    # the in-app ``Subscription`` / ``ShareDelivery`` flow. Read by
    # ``ShareDemandService._resolve_backend`` and by the
    # CommissioningSidebar to switch the upload-related UI on.
    uploads_weekly_share_amount = models.BooleanField(default=False)

    # Tax rates (defaults for new pricing records)
    default_tax_rate_articles = models.DecimalField(
        max_digits=5, decimal_places=2, default=7
    )
    default_tax_rate_crates = models.DecimalField(
        max_digits=5, decimal_places=2, default=19
    )
    default_tax_rate_shares = models.DecimalField(
        max_digits=5, decimal_places=2, default=7
    )

    # ---- Member billing settings (used by apps.payments) ----
    BILLING_STRATEGY_EXACT = "EXACT_PER_PERIOD"
    BILLING_STRATEGY_SMOOTHED = "SMOOTHED"
    BILLING_STRATEGY_CHOICES = [
        (BILLING_STRATEGY_EXACT, "Exact per period (count actual deliveries)"),
        (BILLING_STRATEGY_SMOOTHED, "Smoothed across subscription term"),
    ]
    billing_strategy = models.CharField(
        max_length=20,
        choices=BILLING_STRATEGY_CHOICES,
        default=BILLING_STRATEGY_EXACT,
    )
    bills_joker_deliveries = models.BooleanField(
        default=False,
        help_text="If false, ShareDelivery rows with joker_taken=True are not billed.",
    )
    billing_due_day_of_month = models.PositiveSmallIntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(28)],
        help_text=(
            "Day of month the charge is due. Capped at 28 to avoid month-length issues."
        ),
    )
    sepa_collection_day_of_month = models.PositiveSmallIntegerField(
        default=5,
        validators=[MinValueValidator(1), MaxValueValidator(28)],
        help_text=(
            "Default day of month on which the bank should execute SEPA "
            "direct-debit collections. Used to derive the RequestedCollectionDate "
            "when an office user creates a billing run by month. Adjusted "
            "forward for SEPA lead times and TARGET banking days."
        ),
    )

    # ---- GDPR Art. 17 deletion gate ----
    # When True (default), *every* self-service deletion needs an
    # office/admin to approve it after the email-confirm step. This
    # is the safer default — tenants who want the GDPR-clean
    # "without undue delay" baseline can flip it off. Staff/admin
    # personas always need admin approval regardless of this flag
    # (enforced in ``GDPRService.request_deletion``).
    require_admin_approval_for_gdpr_deletion = models.BooleanField(
        default=True,
        help_text=(
            "If on (default), every deletion request needs an "
            "office/admin to approve after the email-confirm step. "
            "Turn off to honour Art. 17 requests automatically once "
            "the user clicks the email link. Staff/admin deletions "
            "always need admin approval regardless of this."
        ),
    )

    requires_paper_signature_for_membership = models.BooleanField(default=False)
    requires_paper_signature_for_sepa_mandate = models.BooleanField(default=False)

    class Meta:
        ordering = ["-valid_from"]
        constraints = [
            # At most one CURRENT (open-ended) settings row per tenant. The DB is
            # the only place that can make a concurrent update_current_settings
            # race impossible; without it, two PUTs could each leave a
            # valid_until=NULL row and get_current_settings() would become
            # non-deterministic.
            models.UniqueConstraint(
                fields=["tenant"],
                condition=Q(valid_until__isnull=True),
                name="tenantsettings_one_current_per_tenant",
            ),
            # An open-ended (valid_until=NULL) row is the CURRENT settings;
            # only a closed row must end no earlier than it starts.
            models.CheckConstraint(
                condition=Q(valid_until__isnull=True)
                | Q(valid_until__gte=F("valid_from")),
                name="tenantsettings_valid_until_after_valid_from",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.tenant.name} ({self.valid_from})"

    def clean(self) -> None:
        super().clean()
        if (
            self.valid_until is not None
            and self.valid_from is not None
            and self.valid_until < self.valid_from
        ):
            raise ValidationError(
                {"valid_until": "valid_until must not be before valid_from."}
            )

    @classmethod
    def get_current_settings(cls, tenant: Tenant) -> TenantSettings | None:
        """Get the currently valid settings for a tenant.

        ``tenant`` must be a real ``Tenant`` row. Under ``schema_context``
        (Huey workers, management commands) ``connection.tenant`` is a
        django-tenants FakeTenant — NOT a Model — and filtering the CharField-PK
        ``tenant`` FK against it str()-coerces to a non-matching value, so this
        would return None indistinguishably from "no settings row yet" and every
        caller would silently fall back to hardcoded defaults (wrong tax rate,
        dropped invoice-number prefix, default payment terms on finalized docs).
        Fail closed instead: resolve a schema-bearing stand-in to its real
        Tenant by ``schema_name``, and raise for anything without one. Fixing
        the chokepoint covers all call sites at once.
        """
        if not isinstance(tenant, Tenant):
            schema_name = getattr(tenant, "schema_name", None)
            if not schema_name:
                raise TypeError(
                    "get_current_settings requires a Tenant instance or a "
                    "schema-bearing stand-in (FakeTenant), got "
                    f"{type(tenant).__name__}"
                )
            tenant = Tenant.objects.filter(schema_name=schema_name).first()
            if tenant is None:
                return None
        return (
            cls.objects.filter(
                Q(valid_until__gt=timezone.now()) | Q(valid_until__isnull=True),
                tenant=tenant,
                valid_from__lte=timezone.now(),
            )
            # Deterministic tie-break (defense-in-depth alongside the
            # one-current-per-tenant constraint): never let two same-valid_from
            # rows resolve differently across reads.
            .order_by("-valid_from", "-created_at", "-id").first()
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert model instance to dictionary for API responses."""
        exclude_fields = {
            "id",
            "tenant",
            "valid_from",
            "valid_until",
            "created_at",
        }

        result: dict[str, Any] = {}
        for field in self._meta.fields:
            if field.name in exclude_fields:
                continue
            value = getattr(self, field.name)
            if value is None:
                result[field.name] = None
            elif hasattr(value, "isoformat"):
                result[field.name] = value.isoformat()
            elif isinstance(field, models.DecimalField):
                # The remaining DecimalFields are percentages / tax rates (not
                # money), so a JSON float is fine. value_one_coop_share is a
                # PositiveIntegerField now and ships as an int via the else.
                result[field.name] = float(value)
            else:
                result[field.name] = value

        return result

    def copy(self) -> TenantSettings:
        """Create an unsaved copy of this TenantSettings instance."""
        field_values: dict[str, Any] = {}
        for field in self._meta.fields:
            if field.name == "id":
                continue
            if field.name == "tenant":
                field_values[field.name] = self.tenant
            else:
                field_values[field.name] = getattr(self, field.name)

        return TenantSettings(**field_values)


class TenantEmailConfig(models.Model):
    """Per-tenant SMTP credentials. Each tenant brings their own SMTP host."""

    tenant = models.OneToOneField(
        "Tenant", on_delete=models.CASCADE, related_name="email_config"
    )

    # SMTP settings
    smtp_host = models.CharField(max_length=255, blank=True, null=True)
    smtp_port = models.IntegerField(default=587, blank=True, null=True)
    smtp_username = models.CharField(max_length=255, blank=True, null=True)
    smtp_password = EncryptedCharField(max_length=500, blank=True, null=True)
    smtp_use_tls = models.BooleanField(default=True)

    # From email settings
    from_email = models.EmailField(
        validators=[EmailValidator()], help_text="Default 'From' email address"
    )
    from_name = models.CharField(
        max_length=255, help_text="Display name for 'From' field"
    )

    # Reply-to email
    reply_to_email = models.EmailField(blank=True, null=True)

    # Accounting email (for sending invoices to accounting systems like DATEV)
    accounting_email = models.EmailField(
        blank=True,
        null=True,
        help_text="Email address for sending invoices to accounting (e.g., DATEV)",
    )

    # Rate limiting
    max_emails_per_hour = models.IntegerField(default=1000)

    # Status
    is_active = models.BooleanField(default=True, db_index=True)
    is_verified = models.BooleanField(
        default=False,
        help_text="Set to True when a test send through this SMTP host succeeds.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tenant_email_config"
        verbose_name = "Tenant Email Configuration"
        verbose_name_plural = "Tenant Email Configurations"

    def __str__(self) -> str:
        return f"{self.tenant.name} - SMTP ({self.smtp_host or 'unset'})"

    @classmethod
    def get_active_for_schema(cls, schema_name: str) -> TenantEmailConfig | None:
        """Scoped chokepoint for a tenant's active email config.

        ``TenantEmailConfig`` lives in ``SHARED_APPS`` (the public schema), so
        it is NOT protected by django-tenants schema isolation — every read
        MUST carry a tenant scope or it would see every tenant's row (incl.
        their encrypted SMTP credentials). Route all per-tenant reads through
        here instead of a bare ``.objects.filter()`` so the scope can't be
        forgotten. Mirrors ``TenantSettings.get_current_settings``."""
        return cls.objects.filter(
            tenant__schema_name=schema_name, is_active=True
        ).first()

    @property
    def has_smtp_configured(self) -> bool:
        """Whether this tenant has its OWN SMTP host set.

        Sending is gated on this: with no host, ``EmailService`` refuses to
        send rather than silently falling back to the platform ``EMAIL_*``
        account. That platform transport is reserved for operator / ops
        alerts (``mail_admins``) — tenant mail goes out through the tenant's
        own SMTP or not at all. An unconfigured tenant simply cannot send.
        """
        return bool((self.smtp_host or "").strip())

    def get_backend_settings(self) -> dict[str, Any]:
        """Return Django SMTP backend settings as a dict."""
        return {
            "EMAIL_BACKEND": "django.core.mail.backends.smtp.EmailBackend",
            "EMAIL_HOST": self.smtp_host,
            "EMAIL_PORT": self.smtp_port,
            "EMAIL_HOST_USER": self.smtp_username,
            "EMAIL_HOST_PASSWORD": self.smtp_password,
            "EMAIL_USE_TLS": self.smtp_use_tls,
        }
