from rest_framework import serializers

from .models import Tenant, TenantEmailConfig, TenantSettings


def _current_settings_dict(obj: Tenant) -> dict:
    """Return the merged current-version overlay from TenantSettings,
    or an empty dict if the tenant has no settings row yet."""
    instance = TenantSettings.get_current_settings(obj)
    return instance.to_dict() if instance else {}


def _merged_settings_dict(obj: Tenant, current_overlay: dict) -> dict:
    """Flat dict consumed by the frontend ``useTenant().getSetting(key)``.

    Combines tenant-level scalars + the already-resolved ``TenantSettings``
    overlay (passed in so the current-settings query isn't run twice per
    serialized tenant — once for ``settings`` and again for
    ``current_settings``).
    """
    merged: dict = {
        "currency": obj.currency,
        "timezone": obj.timezone,
        "tenant_language": obj.tenant_language,
        "date_format": obj.date_format,
        "time_format": obj.time_format,
        "csv_format": obj.csv_format,
        "number_locale": obj.number_locale,
        "navigation": obj.navigation or {},
        "ai": obj.ai or {},
        "allow_upload_for_data_lists": obj.allow_upload_for_data_lists,
    }
    merged.update(current_overlay)
    return merged


class _TenantSettingsOverlayMixin:
    """Shared ``current_settings`` / ``settings`` getters that resolve the
    TenantSettings overlay ONCE per object instead of once per field. Cached
    per object pk on the serializer instance so list responses don't re-query
    per row."""

    def _settings_overlay(self, obj: Tenant) -> dict:
        cache = self.__dict__.setdefault("_settings_overlay_cache", {})
        if obj.pk not in cache:
            cache[obj.pk] = _current_settings_dict(obj)
        return cache[obj.pk]

    def get_current_settings(self, obj: Tenant) -> dict:
        return self._settings_overlay(obj)

    def get_settings(self, obj: Tenant) -> dict:
        return _merged_settings_dict(obj, self._settings_overlay(obj))


class TenantSerializer(_TenantSettingsOverlayMixin, serializers.ModelSerializer):
    """Full tenant payload — staff-only on read, admin-only on write.

    Read by:
      * Office / staff UI (``ConfigurationGeneral``, ``ConfigurationEmail``,
        reseller PDF generation, packing-list PDF headers) — these
        pages need ``iban`` / ``sepa_*`` / ``uid`` /
        ``organic_control_number`` / ``email_for_orders`` to render.
      * Admin UI when PATCHing the same fields.

    NOT read by member / customer pages. ``TenantViewSet.get_serializer_class``
    routes non-staff callers to ``TenantNonStaffReadSerializer`` so those
    fields aren't shipped to roles whose UI doesn't consume them — even
    though the JWT is still tenant-scoped (no cross-tenant leak), the
    operational-internal fields shouldn't ride along on every
    ``useTenant()`` fetch a member or customer makes.

    The ``settings`` / ``current_settings`` overlays previously lived on
    ``CurrentTenantSerializer``; they were moved here so that anonymous
    callers no longer receive tenant operational config.
    """

    current_settings = serializers.SerializerMethodField()
    settings = serializers.SerializerMethodField()

    class Meta:
        model = Tenant
        fields = "__all__"
        # System-owned / routing-critical columns an admin PATCH must never
        # rewrite via this tenant-facing serializer:
        #   * ``schema_name`` is the django-tenants routing key — changing it
        #     desyncs the resolver from the real Postgres schema and breaks
        #     every subsequent request for the tenant.
        #   * ``is_active`` (de)activation is a super-admin-only operation
        #     (``TenantManagementViewSet`` / ``UpdateTenantRequestSerializer``);
        #     a tenant admin flipping it here would self-lock the org out.
        #   * ``id`` is the primary key; ``created_at`` / ``updated_at`` are
        #     auto-managed timestamps.
        read_only_fields = (
            "id",
            "schema_name",
            "is_active",
            "created_at",
            "updated_at",
        )


class TenantNonStaffReadSerializer(
    _TenantSettingsOverlayMixin, serializers.ModelSerializer
):
    """Narrowed tenant payload for non-staff reads (member, customer).

    Carries everything those UIs actually consume:

      * Identity + branding: ``id``, ``schema_name``, ``name``,
        ``description``, ``logo``, ``bio_logo``, ``is_active``
      * Locale / formatting: ``tenant_language``, ``currency``,
        ``timezone``, ``date_format``, ``time_format``, ``csv_format``,
        ``number_locale``, ``fiscal_year_start_month``
      * UX bootstrap: ``navigation``, ``ai``,
        ``allow_upload_for_data_lists``
      * GDPR impressum (rendered by the default privacy-policy template):
        ``address``, ``zip_code``, ``city``, ``country``, ``email``,
        ``phone_number``, ``website``, ``privacy_policy_html``
      * Settings overlay: ``settings`` / ``current_settings`` (so
        ``useTenant().getSetting(...)`` works the same as for staff)

    Deliberately omitted (office/admin-only, none of which any
    member/customer page consumes — confirmed by grep on
    ``src/pages/customer/``, ``src/pages/abos/``, and
    ``src/components/layout/``):

      * Banking: ``iban``, ``sepa_creditor_id``, ``sepa_creditor_name``,
        ``sepa_creditor_bic``
      * VAT identifier: ``uid``
      * Operational-internal: ``email_for_orders``,
        ``organic_control_number``, ``days_until_payment_due``,
        ``created_at``, ``updated_at``

    If a future member/customer feature needs one of those, surface it
    via a dedicated endpoint (e.g. an explicit "SEPA mandate context"
    response) rather than widening this serializer.
    """

    current_settings = serializers.SerializerMethodField()
    settings = serializers.SerializerMethodField()

    class Meta:
        model = Tenant
        fields = [
            # Identity + branding
            "id",
            "schema_name",
            "name",
            "description",
            "logo",
            "bio_logo",
            "is_active",
            # Locale / formatting
            "tenant_language",
            "currency",
            "timezone",
            "date_format",
            "time_format",
            "csv_format",
            "number_locale",
            # GDPR impressum (rendered by the public privacy-policy template)
            "address",
            "zip_code",
            "city",
            "country",
            "email",
            "phone_number",
            "website",
            "privacy_policy_html",
            # Settings overlay
            "settings",
            "current_settings",
        ]


class TenantSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = TenantSettings
        fields = "__all__"


class TenantSettingsToDictSerializer(serializers.ModelSerializer):
    """Response shape of ``TenantSettings.to_dict()``.

    This mirrors ``to_dict()`` exactly — it is NOT the same as
    ``TenantSettingsSerializer`` (``__all__``):

      * the five system fields (``id``, ``tenant``, ``valid_from``,
        ``valid_until``, ``created_at``) are excluded — ``to_dict``
        drops them, so this payload must not declare them;
      * the percentage / tax-rate decimals are NOT money → ``to_dict``
        ships them as JSON floats, so they are re-declared as
        ``FloatField`` here. (``value_one_coop_share`` is a whole-unit
        ``PositiveIntegerField`` and ships as an int — no override.)

    Used to type the ``update_current_settings`` PUT response (which
    returns ``new_settings.to_dict()``).
    """

    # ``to_dict`` ships these non-money DecimalFields as floats, not the
    # 2dp strings a plain ModelSerializer would emit.
    early_payment_discount_percent = serializers.FloatField(allow_null=True)
    default_tax_rate_articles = serializers.FloatField()
    default_tax_rate_crates = serializers.FloatField()
    default_tax_rate_shares = serializers.FloatField()

    class Meta:
        model = TenantSettings
        exclude = ["id", "tenant", "valid_from", "valid_until", "created_at"]


class TenantEmailConfigSerializer(serializers.ModelSerializer):
    """SMTP-only email config. ``smtp_password`` is write-only."""

    smtp_password = serializers.CharField(
        write_only=True, required=False, allow_blank=True, allow_null=True
    )
    has_smtp_password = serializers.SerializerMethodField()

    class Meta:
        model = TenantEmailConfig
        fields = [
            "id",
            "tenant",
            "smtp_host",
            "smtp_port",
            "smtp_username",
            "smtp_password",
            "has_smtp_password",
            "smtp_use_tls",
            "from_email",
            "from_name",
            "reply_to_email",
            "accounting_email",
            "max_emails_per_hour",
            "is_active",
            "is_verified",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "tenant", "is_verified", "created_at", "updated_at"]

    def get_has_smtp_password(self, obj: TenantEmailConfig) -> bool:
        return bool(obj.smtp_password)

    def validate_smtp_host(self, value):
        """Reject SMTP hosts that resolve to internal addresses (SSRF).

        No-ops in dev/test (``SMTP_ALLOW_PRIVATE_HOSTS``); see
        ``apps.shared.smtp_host_validator``. Blank/None pass through.
        """
        from apps.shared.smtp_host_validator import smtp_host_is_blocked

        if smtp_host_is_blocked(value):
            raise serializers.ValidationError(
                "Enter a public SMTP host. Private, loopback, link-local and "
                "reserved addresses are not allowed.",
                code="smtp_host_not_allowed",
            )
        return value

    def validate_smtp_port(self, value):
        """SMTP port must be a valid TCP port (1–65535)."""
        if value is not None and not (1 <= value <= 65535):
            raise serializers.ValidationError(
                "Enter a valid port number between 1 and 65535.",
                code="smtp_port_invalid",
            )
        return value

    def update(self, instance, validated_data):
        smtp_password = validated_data.pop("smtp_password", None)

        if smtp_password:
            instance.smtp_password = smtp_password
            instance.is_verified = False  # reset verification on credential change

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.save()
        return instance


class CurrentTenantSerializer(serializers.ModelSerializer):
    """Pre-login bootstrap payload — **anonymous endpoint**.

    Served at ``GET /api/tenants/current/`` with no authentication. The
    frontend ``TenantContext`` fetches this on app mount, before any user
    has logged in, to render the login / register / forgot-password pages
    with the correct branding (logo, name) and locale.

    Fields here are strictly the minimum the login / register pages need
    — anonymous callers MUST NOT receive IBAN, BIC, SEPA credentials,
    internal email, phone, VAT number, organic-control number, or the
    merged ``TenantSettings`` overlay:

      * Identity: ``id``, ``name``, ``description`` (NOT ``schema_name``
        — anonymous callers must not be able to enumerate internal
        schema identifiers; the auth-gated ``TenantSerializer`` keeps it)
      * Branding: ``logo``, ``bio_logo``
      * i18n bootstrap: ``tenant_language``
      * Tenant-disabled UX: ``is_active``

    Everything else (IBAN/BIC for invoice PDFs, contact info for PDF
    headers, ``settings`` / ``current_settings`` overlays for
    ``getSetting(...)``, etc.) lives on the full ``TenantSerializer``
    served by the auth-gated ``TenantViewSet`` — the React
    ``TenantContext`` re-fetches that after login completes.
    """

    # File fields → absolute URL strings (rest of the serializer is
    # straight model-field passthrough).
    logo = serializers.SerializerMethodField()
    bio_logo = serializers.SerializerMethodField()

    # Friendly Captcha public sitekey — platform-wide, identical for
    # every tenant. Empty string when the feature flag is off, so the
    # frontend can branch on truthiness to decide whether to mount the
    # widget. Never carries the FC secret.
    friendly_captcha_sitekey = serializers.SerializerMethodField()

    class Meta:
        model = Tenant
        fields = [
            "id",
            "name",
            "description",
            "logo",
            "bio_logo",
            "tenant_language",
            "is_active",
            # Privacy policy is public-by-design (GDPR Art. 13/14 information
            # duties — the document must be accessible without authentication).
            # Empty string when no per-tenant override; frontend then falls
            # back to the static template in ``PrivacyPolicyPage.tsx``.
            "privacy_policy_html",
            "friendly_captcha_sitekey",
        ]

    def _file_url(self, file_field) -> str | None:
        return file_field.url if file_field else None

    def get_logo(self, obj: Tenant) -> str | None:
        return self._file_url(obj.logo)

    def get_bio_logo(self, obj: Tenant) -> str | None:
        return self._file_url(obj.bio_logo)

    def get_friendly_captcha_sitekey(self, obj: Tenant) -> str:
        from django.conf import settings

        if not getattr(settings, "FRIENDLY_CAPTCHA_ENABLED", False):
            return ""
        return settings.FRIENDLY_CAPTCHA_SITEKEY or ""
