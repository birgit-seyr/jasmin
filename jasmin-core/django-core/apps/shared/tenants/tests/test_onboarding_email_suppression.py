"""Onboarding mode suppresses tenant emails inside ``EmailService.send_email``.

While ``TenantSettings.onboarding_mode`` is on, an email that is not listed as
still sent renders nothing, opens no SMTP connection, runs no post-send callback
and leaves one ``suppressed`` EmailLog row per recipient, logged at INFO. Login
and security emails, reseller and customer documents, GDPR emails and test sends
still go out. Other suites mock ``send_email`` itself; these tests run below it,
with the SMTP connection swapped for Django's in-memory backend.
"""

from __future__ import annotations

import datetime
import logging
from unittest import mock

import pytest
import time_machine
from django.core import mail
from django.core.cache import cache
from django.core.mail import get_connection
from django.urls import reverse
from django.utils import timezone
from django_tenants.utils import get_public_schema_name, schema_context
from rest_framework import status
from rest_framework.test import APIClient

from apps.commissioning.tests.factories import JasminUserFactory
from apps.notifications.models import EmailLog
from apps.notifications.registry import get_spec
from apps.shared.deferred_email import schedule_deferred_email, send_email_best_effort
from apps.shared.tenants.email_service import EmailService
from apps.shared.tenants.models import Tenant, TenantEmailConfig, TenantSettings
from apps.shared.tenants.onboarding_emails import (
    SLUGS_SENT_IN_ONBOARDING_MODE,
    EmailCategory,
    onboarding_mode_enabled_for_schema,
    sent_in_onboarding_mode,
)
from core.tenant_db import connection

# Member lifecycle emails and office notices: blocked in onboarding mode.
BLOCKED_SLUGS = (
    "accounts.application_approved",
    "accounts.application_rejected",
    "commissioning.member_cancelled",
    "commissioning.trial_converted",
    "commissioning.waiting_list_offer",
    "commissioning.member_self_cancelled_office",
    "commissioning.subscription_renewal_failures_office",
)


@pytest.fixture(autouse=True)
def _frozen_clock():
    # A Monday away from any year boundary.
    with time_machine.travel(datetime.datetime(2026, 7, 13, 12, 0), tick=False):
        yield


def _configure_settings(tenant, *, onboarding_mode: bool) -> None:
    """Open settings row with the mode, started a year before the frozen clock."""
    row = TenantSettings.objects.filter(tenant=tenant, valid_until__isnull=True).first()
    if row is None:
        row = TenantSettings.objects.create(
            tenant=tenant, valid_from=timezone.now() - datetime.timedelta(days=365)
        )
    elif row.valid_from > timezone.now():
        # The frozen clock sits before a row opened in real time; move its start
        # back so ``get_current_settings`` sees it.
        row.valid_from = timezone.now() - datetime.timedelta(days=365)
    row.onboarding_mode = onboarding_mode
    row.save()


@pytest.fixture()
def onboarding_mode(tenant):
    _configure_settings(tenant, onboarding_mode=True)


@pytest.fixture()
def onboarding_mode_off(tenant):
    _configure_settings(tenant, onboarding_mode=False)


@pytest.fixture()
def email_config(tenant):
    return TenantEmailConfig.objects.create(
        tenant=tenant,
        smtp_host="localhost",
        smtp_port=25,
        smtp_use_tls=False,
        from_email="noreply@example.org",
        from_name="Test Tenant",
        is_active=True,
        is_verified=True,
    )


@pytest.fixture()
def smtp_connection():
    """Swap the tenant SMTP connection for the in-memory backend. The mock
    records whether a connection was asked for at all."""
    mail.outbox.clear()
    # The test-send endpoints are throttled per tenant through the cache.
    cache.clear()
    in_memory = get_connection(backend="django.core.mail.backends.locmem.EmailBackend")
    with mock.patch.object(
        EmailService, "_get_connection", return_value=in_memory
    ) as connection_mock:
        yield connection_mock
    cache.clear()


def _send(
    service: EmailService,
    slug: str,
    *,
    category: EmailCategory = EmailCategory.GENERAL,
    to_emails: tuple[str, ...] = ("maria@example.org",),
) -> bool:
    return service.send_email(
        slug=slug,
        to_emails=list(to_emails),
        context=dict(get_spec(slug).sample),
        language="en",
        related_object_type="member",
        related_object_id="member-1",
        category=category,
    )


def _statuses() -> list[str]:
    return sorted(EmailLog.objects.values_list("status", flat=True))


class TestStillSentList:
    def test_every_still_sent_slug_is_registered(self):
        for slug in SLUGS_SENT_IN_ONBOARDING_MODE:
            get_spec(slug)

    @pytest.mark.parametrize("slug", BLOCKED_SLUGS)
    def test_member_emails_and_office_notices_are_blocked(self, slug):
        get_spec(slug)
        assert sent_in_onboarding_mode(slug, EmailCategory.GENERAL) is False

    def test_an_unlisted_slug_is_blocked(self):
        assert (
            sent_in_onboarding_mode(
                "commissioning.not_written_yet", EmailCategory.GENERAL
            )
            is False
        )

    @pytest.mark.parametrize("slug", ["accounts.invitation", "accounts.welcome_user"])
    def test_member_lifecycle_category_blocks_a_login_slug(self, slug):
        assert sent_in_onboarding_mode(slug, EmailCategory.GENERAL) is True
        assert sent_in_onboarding_mode(slug, EmailCategory.MEMBER_LIFECYCLE) is False

    @pytest.mark.parametrize(
        "slug", ["commissioning.member_cancelled", "tenants.smtp_test"]
    )
    def test_test_send_category_is_always_sent(self, slug):
        assert sent_in_onboarding_mode(slug, EmailCategory.TEST_SEND) is True


@pytest.mark.django_db
class TestOnboardingModeRead:
    def test_on(self, tenant, onboarding_mode):
        assert onboarding_mode_enabled_for_schema(tenant.schema_name) is True

    def test_off(self, tenant, onboarding_mode_off):
        assert onboarding_mode_enabled_for_schema(tenant.schema_name) is False

    def test_no_settings_row_is_off(self, tenant):
        TenantSettings.objects.filter(tenant=tenant).delete()
        assert onboarding_mode_enabled_for_schema(tenant.schema_name) is False

    def test_a_fake_tenant_under_schema_context_is_read(self, tenant, onboarding_mode):
        with schema_context(tenant.schema_name):
            assert not isinstance(connection.tenant, Tenant)
            assert onboarding_mode_enabled_for_schema(tenant.schema_name) is True

    def test_another_schema_than_the_active_one_is_read(self, tenant, onboarding_mode):
        with schema_context(get_public_schema_name()):
            assert onboarding_mode_enabled_for_schema(tenant.schema_name) is True

    def test_public_and_unknown_schemas_are_off(self, tenant, onboarding_mode):
        assert onboarding_mode_enabled_for_schema(get_public_schema_name()) is False
        assert onboarding_mode_enabled_for_schema("no_such_schema") is False


@pytest.mark.django_db
class TestSuppressedSend:
    def test_a_member_email_is_suppressed_while_on(
        self, tenant, onboarding_mode, email_config, smtp_connection
    ):
        service = EmailService(tenant.schema_name)

        with (
            mock.patch.object(EmailService, "_render_body", autospec=True) as render,
            mock.patch("apps.shared.tenants.email_service.logger") as service_logger,
        ):
            sent = _send(
                service,
                "commissioning.member_cancelled",
                to_emails=("maria@example.org", "lukas@example.org"),
            )

        assert sent is False
        assert service.last_send_suppressed is True
        assert mail.outbox == []
        smtp_connection.assert_not_called()
        render.assert_not_called()
        rows = list(EmailLog.objects.order_by("recipient"))
        assert [row.recipient for row in rows] == [
            "lukas@example.org",
            "maria@example.org",
        ]
        for row in rows:
            assert row.status == "suppressed"
            assert row.template == "commissioning.member_cancelled"
            assert row.purpose == "commissioning.member_cancelled"
            assert row.related_object_type == "member"
            assert row.related_object_id == "member-1"
            assert row.error == "onboarding_mode"
            assert row.subject == ""
            assert row.sent_at is None
        service_logger.info.assert_called_once()
        assert service_logger.info.call_args.args[0].startswith(
            "Email suppressed in onboarding mode"
        )
        service_logger.error.assert_not_called()
        service_logger.warning.assert_not_called()

    def test_the_same_email_is_sent_while_off(
        self, tenant, onboarding_mode_off, email_config, smtp_connection
    ):
        service = EmailService(tenant.schema_name)

        assert _send(service, "commissioning.member_cancelled") is True
        assert service.last_send_suppressed is False
        assert len(mail.outbox) == 1
        assert _statuses() == ["sent"]

    def test_the_same_email_is_sent_without_a_settings_row(
        self, tenant, email_config, smtp_connection
    ):
        TenantSettings.objects.filter(tenant=tenant).delete()

        assert _send(EmailService(tenant.schema_name), "commissioning.member_cancelled")
        assert len(mail.outbox) == 1
        assert _statuses() == ["sent"]

    def test_a_worker_send_under_schema_context_is_suppressed(
        self, tenant, onboarding_mode, email_config, smtp_connection
    ):
        with schema_context(tenant.schema_name):
            assert not isinstance(connection.tenant, Tenant)
            service = EmailService()
            sent = _send(service, "commissioning.subscription_renewal_failures_office")

        assert sent is False
        assert service.last_send_suppressed is True
        assert mail.outbox == []
        assert _statuses() == ["suppressed"]

    def test_no_email_log_row_outside_the_tenant_schema(
        self, tenant, onboarding_mode, email_config, smtp_connection
    ):
        service = EmailService(tenant.schema_name)

        with schema_context(get_public_schema_name()):
            sent = _send(service, "commissioning.member_cancelled")

        assert sent is False
        assert service.last_send_suppressed is True
        assert mail.outbox == []
        assert EmailLog.objects.count() == 0

    @pytest.mark.parametrize("slug", sorted(SLUGS_SENT_IN_ONBOARDING_MODE))
    def test_login_reseller_and_gdpr_emails_are_sent_while_on(
        self, tenant, onboarding_mode, email_config, smtp_connection, slug
    ):
        service = EmailService(tenant.schema_name)

        assert _send(service, slug) is True
        assert service.last_send_suppressed is False
        assert len(mail.outbox) == 1
        assert _statuses() == ["sent"]

    @pytest.mark.parametrize("slug", ["accounts.invitation", "accounts.welcome_user"])
    def test_a_member_flow_send_of_a_login_slug_is_suppressed_while_on(
        self, tenant, onboarding_mode, email_config, smtp_connection, slug
    ):
        member_flow = EmailService(tenant.schema_name)
        login_flow = EmailService(tenant.schema_name)

        assert (
            _send(member_flow, slug, category=EmailCategory.MEMBER_LIFECYCLE) is False
        )
        assert member_flow.last_send_suppressed is True
        assert _send(login_flow, slug) is True
        assert len(mail.outbox) == 1
        assert _statuses() == ["sent", "suppressed"]

    def test_a_test_send_of_a_blocked_slug_is_sent_while_on(
        self, tenant, onboarding_mode, email_config, smtp_connection
    ):
        service = EmailService(tenant.schema_name)

        assert _send(
            service, "commissioning.member_cancelled", category=EmailCategory.TEST_SEND
        )
        assert len(mail.outbox) == 1
        assert _statuses() == ["sent"]


def _best_effort_kwargs(caller_logger, callback) -> dict:
    slug = "commissioning.member_cancelled"
    return {
        "slug": slug,
        "to_emails": ["maria@example.org"],
        "context": dict(get_spec(slug).sample),
        "related_object_type": "member",
        "related_object_id": "member-1",
        "logger": caller_logger,
        "log_error_event": "member_cancelled.email_failed",
        "log_not_sent_event": "member_cancelled.email_not_sent",
        "log_ref": "member=member-1",
        "post_send_callback": callback,
    }


@pytest.mark.django_db
class TestBestEffortWrappers:
    def test_a_suppressed_send_logs_info_and_runs_no_callback(
        self, tenant, onboarding_mode, email_config, smtp_connection
    ):
        caller_logger = mock.Mock(spec=logging.Logger)
        callback = mock.Mock()

        sent = send_email_best_effort(**_best_effort_kwargs(caller_logger, callback))

        assert sent is False
        callback.assert_not_called()
        caller_logger.info.assert_called_once_with(
            "%s %s reason=onboarding_mode",
            "member_cancelled.email_not_sent",
            "member=member-1",
        )
        caller_logger.error.assert_not_called()
        caller_logger.warning.assert_not_called()
        assert mail.outbox == []
        assert _statuses() == ["suppressed"]

    def test_a_deferred_send_reads_the_flag_when_it_runs(
        self,
        tenant,
        onboarding_mode_off,
        email_config,
        smtp_connection,
        django_capture_on_commit_callbacks,
    ):
        caller_logger = mock.Mock(spec=logging.Logger)
        callback = mock.Mock()
        kwargs = _best_effort_kwargs(caller_logger, callback)
        kwargs.pop("post_send_callback")

        with django_capture_on_commit_callbacks(execute=True):
            schedule_deferred_email(**kwargs, post_send_callback=callback)
            _configure_settings(tenant, onboarding_mode=True)

        callback.assert_not_called()
        caller_logger.error.assert_not_called()
        caller_logger.info.assert_called_once()
        assert mail.outbox == []
        assert _statuses() == ["suppressed"]

    def test_a_real_failure_still_logs_an_error(
        self, tenant, onboarding_mode_off, email_config
    ):
        caller_logger = mock.Mock(spec=logging.Logger)
        callback = mock.Mock()

        with mock.patch.object(
            EmailService, "_build_and_send", autospec=True, return_value=False
        ):
            sent = send_email_best_effort(
                **_best_effort_kwargs(caller_logger, callback)
            )

        assert sent is False
        callback.assert_not_called()
        caller_logger.error.assert_called_once_with(
            "%s %s", "member_cancelled.email_not_sent", "member=member-1"
        )
        caller_logger.info.assert_not_called()


@pytest.fixture(params=["no_config", "blank_smtp_host"])
def email_not_set_up(request, tenant):
    """A tenant that has not set up SMTP yet: no email config at all, or the
    active config the email settings page creates, with no SMTP host."""
    TenantEmailConfig.objects.filter(tenant=tenant).delete()
    if request.param == "blank_smtp_host":
        TenantEmailConfig.objects.create(tenant=tenant, smtp_host="", is_active=True)
    return request.param


@pytest.mark.django_db
class TestSuppressedSendWithoutSmtpSetup:
    """Onboarding mode decides before the email config is read, so a member
    email is suppressed and logged at INFO even while SMTP is not set up."""

    def test_the_send_is_suppressed_without_an_error(
        self, tenant, onboarding_mode, email_not_set_up, smtp_connection
    ):
        with mock.patch("apps.shared.tenants.email_service.logger") as service_logger:
            service = EmailService(tenant.schema_name)
            sent = _send(service, "commissioning.member_cancelled")

        assert sent is False
        assert service.last_send_suppressed is True
        smtp_connection.assert_not_called()
        assert mail.outbox == []
        row = EmailLog.objects.get()
        assert (row.status, row.recipient) == ("suppressed", "maria@example.org")
        service_logger.info.assert_called_once()
        service_logger.error.assert_not_called()
        service_logger.warning.assert_not_called()

    def test_the_best_effort_wrapper_logs_info(
        self, tenant, onboarding_mode, email_not_set_up, smtp_connection
    ):
        caller_logger = mock.Mock(spec=logging.Logger)
        callback = mock.Mock()

        with mock.patch("apps.shared.tenants.email_service.logger") as service_logger:
            sent = send_email_best_effort(
                **_best_effort_kwargs(caller_logger, callback)
            )

        assert sent is False
        callback.assert_not_called()
        caller_logger.info.assert_called_once_with(
            "%s %s reason=onboarding_mode",
            "member_cancelled.email_not_sent",
            "member=member-1",
        )
        caller_logger.error.assert_not_called()
        service_logger.error.assert_not_called()
        service_logger.warning.assert_not_called()
        smtp_connection.assert_not_called()
        assert _statuses() == ["suppressed"]

    def test_without_the_mode_the_send_still_fails_for_lack_of_smtp(
        self, tenant, onboarding_mode_off, email_not_set_up, smtp_connection
    ):
        service = EmailService(tenant.schema_name)

        assert _send(service, "commissioning.member_cancelled") is False
        assert service.last_send_suppressed is False
        smtp_connection.assert_not_called()
        assert EmailLog.objects.count() == 0


@pytest.mark.django_db
class TestTestSendsWhileOn:
    def test_the_smtp_test_is_sent_and_verifies_the_config(
        self, api_client, user, onboarding_mode, email_config, smtp_connection
    ):
        email_config.is_verified = False
        email_config.save(update_fields=["is_verified"])

        resp = api_client.post(
            reverse("tenant_email_config-test-email"),
            {"to_email": user.email},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert len(mail.outbox) == 1
        email_config.refresh_from_db()
        assert email_config.is_verified is True
        row = EmailLog.objects.get()
        assert (row.status, row.purpose) == ("sent", "test:smtp")

    def test_a_template_test_send_of_a_member_email_is_sent(
        self, tenant, onboarding_mode, email_config, smtp_connection
    ):
        admin = JasminUserFactory(roles=["admin"])
        client = APIClient(HTTP_HOST="tenants-pytest.localhost")
        client.force_authenticate(user=admin)

        resp = client.post(
            reverse(
                "email-template-test-send",
                kwargs={"slug": "commissioning.member_cancelled"},
            ),
            {},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert len(mail.outbox) == 1
        row = EmailLog.objects.get()
        assert (row.status, row.purpose) == (
            "sent",
            "test:commissioning.member_cancelled",
        )
