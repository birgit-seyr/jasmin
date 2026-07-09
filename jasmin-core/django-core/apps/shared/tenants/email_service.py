import logging
import smtplib
import uuid

from django.core.mail import EmailMultiAlternatives
from django.template import TemplateDoesNotExist, TemplateSyntaxError
from django.template.loader import render_to_string
from django.utils import timezone

from .models import TenantEmailConfig

logger = logging.getLogger(__name__)

# Mirrors EmailLog.subject / EmailTemplate.subject CharField max_length — the
# rendered subject is truncated to this before logging so the DB never silently
# cuts it.
_SUBJECT_MAX_LENGTH = 512


def _build_message_id(from_email: str) -> str:
    """Generate an RFC 5322 ``Message-ID`` header for an outgoing email.

    Format is ``<uuid4@domain>``. The ``domain`` is taken from the
    ``from_email`` so bounce processors / Postfix logs can correlate
    the ID against the sending tenant's mail domain. Falls back to
    ``jasmin.local`` if ``from_email`` has no ``@`` (mis-configured
    tenant).
    """
    domain = from_email.rsplit("@", 1)[-1].strip() if "@" in from_email else ""
    if not domain:
        domain = "jasmin.local"
    return f"<{uuid.uuid4()}@{domain}>"


def capture_tenant_email_context() -> dict:
    """Snapshot the current (real) tenant's email-relevant attributes.

    Call this in a request / synchronous context where ``connection.tenant``
    is a real :class:`Tenant`. The returned dict is JSON-safe and meant to be
    threaded through Huey ``task_kwargs`` to a worker, where
    ``connection.tenant`` is a ``FakeTenant`` exposing only ``schema_name`` /
    ``tenant_type`` — so ``name`` / ``tenant_language`` / ``domains`` are NOT
    recoverable on the worker. Bulk-send tasks therefore capture this at
    enqueue time and pass it through instead of reading ``connection.tenant``.

    Keys: ``tenant_name``, ``tenant_language`` (2-char, may be ``""``),
    ``bank_details`` (``"IBAN / BIC"``), ``frontend_base_url``.
    """
    from django.db import connection

    from apps.shared.tenant_urls import frontend_base_url, tenant_name

    tenant = getattr(connection, "tenant", None)
    language = ((getattr(tenant, "tenant_language", "") or "").strip().lower())[:2]
    iban = (getattr(tenant, "iban", "") or "") if tenant else ""
    bic = (getattr(tenant, "sepa_creditor_bic", "") or "") if tenant else ""
    bank_details = " / ".join(part for part in [iban, bic] if part)

    return {
        "tenant_name": tenant_name(),
        "tenant_language": language,
        "bank_details": bank_details,
        "frontend_base_url": frontend_base_url(),
    }


def _resolve_template(
    slug: str,
    context: dict,
    language: str,
    *,
    language_explicit: bool = False,
) -> tuple[str, str, str, str]:
    """Return (subject_template, html, text, log_template_name).

    Lookup order for a given (slug, language):
        1. DB override for (slug, language) — safe Mustache renderer.
        2. DB override for (slug, DEFAULT_LANGUAGE) — safe Mustache.
        3. File ``<stem>.<language>.html`` — Django renderer.
        4. File ``<stem>.<DEFAULT_LANGUAGE>.html`` — Django renderer.
    Same fallback applies independently to .html and .txt.

    ``language_explicit`` marks a language the caller asked for by name
    (e.g. the recipient's ``user_language``) rather than one resolved
    from the tenant default. An explicitly requested language must win:
    steps 2 and 3 swap, so the shipped requested-language file outranks
    a DB override in the fallback language. With ``language_explicit=
    False`` the order above is unchanged.
    """
    from apps.notifications import template_renderer
    from apps.notifications.models import EmailTemplate
    from apps.notifications.registry import (
        DEFAULT_LANGUAGE,
        get_spec,
        template_path,
    )

    spec = get_spec(slug)

    # EML-5: pick the subject in the send language so it matches the (per-language)
    # body. ``default_subject`` is German; ``default_subject_en`` (when set) is the
    # English one. Mirrors the body's language fallback (→ German default).
    default_subject = (
        spec.default_subject_en
        if language == "en" and spec.default_subject_en
        else spec.default_subject
    )

    # 1 & 2: DB override (requested lang, then fallback lang) in a SINGLE query.
    # A deterministic rank (requested=0, fallback=1) picks the preferred row —
    # not an alphabetical order_by, which would only happen to work for some
    # code pairs.
    from django.db.models import Case, IntegerField, Q, Value, When

    override = (
        EmailTemplate.objects.filter(
            Q(language=language) | Q(language=DEFAULT_LANGUAGE),
            slug=slug,
            is_customized=True,
        )
        .annotate(
            _lang_rank=Case(
                When(language=language, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        .order_by("_lang_rank")
        .first()
    )

    # Shipped Django template for a single (language, ext); None on miss.
    def _render_file(lang: str, ext: str) -> str | None:
        try:
            return render_to_string(
                template_path(spec.default_template, lang, ext), context
            )
        except (
            TemplateDoesNotExist,
            TemplateSyntaxError,
            ValueError,
            TypeError,
            OSError,
        ):
            return None

    if override and override.body_html:
        # An explicitly requested language must win: when the only DB
        # override is in the fallback language, the shipped file in the
        # requested language outranks it — otherwise a tenant's German
        # override would shadow the shipped English body on an explicit
        # English send.
        if language_explicit and override.language != language:
            requested_file_html = _render_file(language, "html")
            if requested_file_html is not None:
                return (
                    default_subject,
                    requested_file_html,
                    _render_file(language, "txt") or "",
                    slug,
                )
        html = template_renderer.render(override.body_html, context)
        text = (
            template_renderer.render(override.body_text, context)
            if override.body_text
            else ""
        )
        subject_tpl = override.subject or default_subject
        return subject_tpl, html, text, slug

    # 3 & 4: shipped Django template, with fallback to default lang.
    def _render_or_fallback(ext: str) -> str:
        for lang in (language, DEFAULT_LANGUAGE):
            rendered = _render_file(lang, ext)
            if rendered is not None:
                return rendered
        return ""

    html = _render_or_fallback("html")
    text = _render_or_fallback("txt")
    return default_subject, html, text, slug


class EmailService:
    """Service for sending emails in multi-tenant environment.

    Constructed with the tenant's ``schema_name`` (defaults to the active
    request's schema). Note that this is the django-tenants schema name,
    NOT ``Tenant.id`` — :class:`TenantEmailConfig` is therefore looked up
    via ``tenant__schema_name``.
    """

    def __init__(self, schema_name: str | None = None):
        if schema_name is None:
            from django.db import connection

            schema_name = connection.tenant.schema_name
        self.schema_name = schema_name
        self.config = self._get_config()

    def _get_config(self) -> TenantEmailConfig | None:
        """Get tenant email config from the DB.

        Previously cached for 1 hour, but the cache created a real
        invalidation hazard (admin updates SMTP creds → emails go to the
        old SMTP for an hour) for a marginal perf win (~1ms per send).
        Drop the cache; revisit if a future bulk-send workload makes
        per-send DB lookup hot. See docs/code/engineering-audit-playbook.md, Caching
        invalidation pass.
        """
        # Scoped chokepoint (TenantEmailConfig is a SHARED/public-schema table
        # — never read it without a tenant scope).
        config = TenantEmailConfig.get_active_for_schema(self.schema_name)
        if config is None:
            logger.error(f"No email config found for tenant {self.schema_name}")
        return config

    def send_email(
        self,
        to_emails: list[str],
        context: dict,
        slug: str,
        subject: str | None = None,
        from_email: str | None = None,
        from_name: str | None = None,
        reply_to: str | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        attachments: list[tuple] | None = None,
        priority: str = "normal",
        purpose: str = "",
        related_object_type: str = "",
        related_object_id: str = "",
        language: str | None = None,
    ) -> bool:
        """Send an email using tenant's configuration.

        ``slug`` is the registry key (e.g. ``"accounts.welcome_user"``); the
        tenant can override the template through the admin UI.

        ``language`` selects which (slug, language) override / file to
        render. If omitted, falls back to the tenant's
        ``tenant_language``, then to the registry's ``DEFAULT_LANGUAGE``
        ("en"). Missing per-language files fall back to the default
        language automatically.

        ``subject`` may be provided explicitly; otherwise it is derived
        from the slug's default (or the tenant override) and rendered
        with the same context.
        """
        if not self.config:
            logger.error(f"Cannot send email: no config for tenant {self.schema_name}")
            return False

        # A tenant with no SMTP host of its own has email sending disabled —
        # we do NOT fall back to the platform ``EMAIL_*`` account (reserved for
        # ops alerts). Skip before rendering/logging; nothing goes out.
        if not self.config.has_smtp_configured:
            logger.warning(
                "Email sending disabled for tenant %s: no SMTP host configured",
                self.schema_name,
            )
            return False

        if not self.config.is_verified:
            logger.warning(f"Email domain not verified for tenant {self.schema_name}")

        # Use config defaults if not provided
        from_email = from_email or self.config.from_email
        from_name = from_name or self.config.from_name
        reply_to = reply_to or self.config.reply_to_email

        # Format from address with name
        from_address = f"{from_name} <{from_email}>"

        language, language_explicit = self._resolve_send_language(language)

        rendered = self._render_body(
            slug, context, language, language_explicit=language_explicit
        )
        if rendered is None:
            return False
        subject_tpl, html_content, text_content, log_template_name = rendered

        subject = self._resolve_subject(subject, subject_tpl, context, slug)

        # RFC 5322 Message-ID — one ID per *outgoing message*, not per
        # recipient. We stamp the same header on every EmailLog row so
        # bounce / DSN handlers can map an inbound complaint back to
        # the full set of intended recipients regardless of which row
        # the bounce was attributed to. (P1-4)
        message_id = _build_message_id(from_email)

        return self._build_and_send(
            to_emails=to_emails,
            subject=subject,
            text_content=text_content,
            html_content=html_content,
            from_address=from_address,
            reply_to=reply_to,
            cc=cc,
            bcc=bcc,
            attachments=attachments,
            priority=priority,
            message_id=message_id,
            log_template_name=log_template_name,
            purpose=purpose,
            slug=slug,
            related_object_type=related_object_type,
            related_object_id=related_object_id,
        )

    def _resolve_send_language(self, language: str | None) -> tuple[str, bool]:
        """Resolve the effective send language and whether it was explicit.

        Resolution order: explicit (normalized) > tenant default >
        ``DEFAULT_LANGUAGE``. ``normalize_language`` maps aliases ('deu',
        'de-DE', 'german', …) to a SUPPORTED code and returns None for
        anything unsupported — so an explicit but invalid ``user_language``
        (the field is an unvalidated CharField) falls through to the
        tenant/default resolution instead of silently mis-resolving the
        template.

        The returned ``language_explicit`` flag is True when the caller
        named a language that normalized to a supported code — the resolver
        lets the shipped file in that language outrank a fallback-language DB
        override. A language resolved from the tenant default keeps the plain
        order.
        """
        from apps.notifications.registry import DEFAULT_LANGUAGE, normalize_language

        language = normalize_language(language)
        language_explicit = language is not None
        if language is None:
            try:
                from django.db import connection

                tenant = getattr(connection, "tenant", None)
                language = normalize_language(getattr(tenant, "tenant_language", None))
            except (AttributeError, ValueError, TypeError):
                # Tenant context missing / mis-shaped (test setup, public
                # schema, ...). Any other exception is a real bug worth
                # crashing on.
                language = None
        if language is None:
            language = DEFAULT_LANGUAGE
        return language, language_explicit

    def _render_body(
        self,
        slug: str,
        context: dict,
        language: str,
        *,
        language_explicit: bool,
    ) -> tuple[str, str, str, str] | None:
        """Render (subject_tpl, html, text, log_template_name) for the send.

        Returns None (not a tuple) when template rendering fails, so the
        caller can short-circuit with ``return False``.
        """
        try:
            return _resolve_template(
                slug, context, language, language_explicit=language_explicit
            )
        except (
            TemplateDoesNotExist,
            TemplateSyntaxError,
            ValueError,
            TypeError,
            AttributeError,
            OSError,
        ) as exc:
            # Template render failed (missing file, syntax error,
            # context-key mismatch, ...) — log and bail. Anything outside
            # this set is a real bug and should propagate.
            logger.error(
                f"Failed to render email (slug={slug!r}): {exc}",
                exc_info=True,
            )
            return None

    @staticmethod
    def _resolve_subject(
        subject: str | None,
        subject_tpl: str,
        context: dict,
        slug: str,
    ) -> str:
        """Render (when not explicitly given) and length-cap the subject."""
        if subject is None:
            # Render the subject template through the safe renderer too,
            # so tenant-edited subjects can use {{vars}}.
            from apps.notifications import template_renderer

            subject = (
                template_renderer.render_subject(subject_tpl, context)
                if subject_tpl
                else ""
            )

        # The rendered subject must fit EmailLog.subject / EmailTemplate.subject
        # (CharField max_length=512). Truncate + warn rather than let the DB
        # silently cut it, which would corrupt the audit trail with no signal.
        if subject and len(subject) > _SUBJECT_MAX_LENGTH:
            logger.warning(
                "Email subject truncated to %d chars (slug=%r)",
                _SUBJECT_MAX_LENGTH,
                slug,
            )
            subject = subject[:_SUBJECT_MAX_LENGTH]
        return subject

    def _build_and_send(
        self,
        *,
        to_emails: list[str],
        subject: str,
        text_content: str,
        html_content: str,
        from_address: str,
        reply_to: str | None,
        cc: list[str] | None,
        bcc: list[str] | None,
        attachments: list[tuple] | None,
        priority: str,
        message_id: str,
        log_template_name: str,
        purpose: str,
        slug: str,
        related_object_type: str,
        related_object_id: str,
    ) -> bool:
        """Assemble the message, write EmailLog rows, send, and record status.

        Returns True on a successful send, False on an SMTP / connection /
        config failure (which is logged and stamped onto any rows created).
        """
        from apps.notifications.models import EmailLog

        # Rows are created only AFTER message setup succeeds (just before send),
        # so a failure in connection / header / attachment setup can no longer
        # leave behind a "pending" EmailLog that never transitions to a final
        # status (the cleanup task keeps pending rows forever). The log lives in
        # the current tenant schema — schema separation enforces isolation.
        log_rows: list[EmailLog] = []
        try:
            # Create email message
            email = EmailMultiAlternatives(
                subject=subject,
                body=text_content,
                from_email=from_address,
                to=to_emails,
                cc=cc,
                bcc=bcc,
                reply_to=[reply_to] if reply_to else None,
                connection=self._get_connection(),
            )

            # Stamp the RFC 5322 Message-ID so we control the value Postfix
            # (and downstream MTAs) record in their logs. Without this,
            # Django would let Python's email lib generate one at send-time
            # — but that ID never gets stored on our EmailLog rows, so
            # correlating bounces back to the row would be impossible.
            email.extra_headers["Message-ID"] = message_id

            # Attach HTML version
            email.attach_alternative(html_content, "text/html")

            # Add attachments if provided
            if attachments:
                for filename, content, mimetype in attachments:
                    email.attach(filename, content, mimetype)

            # Set priority headers
            if priority == "high":
                email.extra_headers["X-Priority"] = "1"
                email.extra_headers["Importance"] = "high"
            elif priority == "low":
                email.extra_headers["X-Priority"] = "5"
                email.extra_headers["Importance"] = "low"

            # Setup is done — create the audit rows now (one INSERT for all
            # recipients), then stamp the breadcrumb header from their IDs.
            log_rows = [
                EmailLog(
                    recipient=addr,
                    subject=subject,
                    template=log_template_name,
                    purpose=purpose or (slug or ""),
                    related_object_type=related_object_type,
                    related_object_id=related_object_id,
                    provider_message_id=message_id,
                    status="pending",
                )
                for addr in to_emails
            ]
            EmailLog.objects.bulk_create(log_rows)
            email.extra_headers["X-Jasmin-Log-Ids"] = ",".join(
                str(r.id) for r in log_rows
            )

            # Send email
            email.send(fail_silently=False)

            # One UPDATE for the whole batch instead of one save() per row.
            EmailLog.objects.filter(pk__in=[r.pk for r in log_rows]).update(
                status="sent", sent_at=timezone.now()
            )

            # NB: recipient addresses + the tenant-rendered subject are PII and
            # already live in the EmailLog rows (the audit store). Logging them
            # here would leak them into app.log / stdout / error-tracker
            # breadcrumbs, beyond the reach of the GDPR scrub (which cleans the
            # DB row, not log files). Log the non-PII shape + the EmailLog pks
            # so a row can still be correlated.
            logger.info(
                "Email sent: recipients=%d tenant=%s purpose=%s log_ids=%s",
                len(to_emails),
                self.schema_name,
                purpose or "-",
                ",".join(str(r.id) for r in log_rows),
            )
            return True

        except (
            smtplib.SMTPException,
            ConnectionError,
            OSError,
            TimeoutError,
            ValueError,
            TypeError,
        ) as exc:
            # SMTP / connection / config failure. Mark every row we DID create
            # as failed (none if setup failed before bulk_create — so no
            # orphaned pending rows), then return False. Real bugs propagate.
            if log_rows and log_rows[0].pk is not None:
                EmailLog.objects.filter(pk__in=[r.pk for r in log_rows]).update(
                    status="failed", error=str(exc)[:2000]
                )
            # Same PII reasoning as the success line above — no recipient
            # addresses in the message. ``exc_info`` is kept for debugging the
            # delivery failure (the SMTP exception may itself name a recipient,
            # but that detail is operationally necessary and stays in the
            # traceback, not in a routine PII-bearing field).
            logger.error(
                "Failed to send email: recipients=%d tenant=%s purpose=%s "
                "log_ids=%s",
                len(to_emails),
                self.schema_name,
                purpose or "-",
                ",".join(str(r.id) for r in log_rows) if log_rows else "-",
                exc_info=True,
            )
            return False

    def _get_connection(self):
        """Open a Django SMTP connection from this tenant's stored creds."""
        from django.conf import settings
        from django.core.mail import get_connection

        from apps.shared.smtp_host_validator import smtp_host_is_blocked

        s = self.config.get_backend_settings()

        # No platform fallback. Django's ``get_connection(host=None, …)`` would
        # silently fall back to ``settings.EMAIL_HOST`` (the platform account,
        # reserved for ops alerts) — refuse instead. ``send_email`` already
        # guards on ``has_smtp_configured`` before reaching here; this is the
        # authoritative backstop so no internal caller can reintroduce the
        # fallback. Caught by the send paths' except blocks → logged, False.
        if not (s["EMAIL_HOST"] or "").strip():
            raise ValueError(
                "No SMTP host configured for this tenant; refusing to fall "
                "back to the platform email account."
            )

        # Authoritative SSRF guard: re-check the tenant-supplied host at
        # send time. Write-time validation trusts a DNS resolution the
        # office user controls, and pre-existing configs were never
        # validated. A ``ValueError`` here is caught by ``send_email``'s
        # except block, so a blocked host fails gracefully (logged, send
        # returns False) exactly like an unreachable host, on every send path.
        if smtp_host_is_blocked(s["EMAIL_HOST"]):
            raise ValueError(
                f"SMTP host {s['EMAIL_HOST']!r} resolves to a private or "
                f"otherwise disallowed address; refusing to connect."
            )

        return get_connection(
            backend=s["EMAIL_BACKEND"],
            host=s["EMAIL_HOST"],
            port=s["EMAIL_PORT"],
            username=s["EMAIL_HOST_USER"],
            password=s["EMAIL_HOST_PASSWORD"],
            use_tls=s["EMAIL_USE_TLS"],
            # Cap the connect/handshake so a slow/unreachable host can't
            # hang the worker (no timeout = block forever).
            timeout=getattr(settings, "EMAIL_TIMEOUT", 10),
        )
