"""Task-wrapper coverage for ``daily_subscription_renewals`` (TEST-5).

``test_renewal.py`` covers the SERVICE (``run_renewals``) and the digest helper,
but nothing between them: the Huey task's per-tenant opt-out gate, the settings
wiring, and the failed→digest handoff. The gate is a double negative
(``if not settings or not settings.subscriptions_are_auto_renewed: return``);
flipping it, or reading a wrong-but-existing settings field, type-checks and
passes the whole suite while renewals silently invert in production. These pin
the wrapper.

The nested ``run(tenant)`` runs under ``for_each_tenant`` inside a schema
context, so we drive the real task via ``.call_local()`` and patch its
collaborators at the names the closure resolves: ``run_renewals`` in the
renewal service module (imported inside ``run``), the digest helper + settings
accessor in ``apps.commissioning.tasks``.
"""

from __future__ import annotations

import datetime
from unittest.mock import Mock, patch

import pytest

pytestmark = pytest.mark.django_db

_TASKS = "apps.commissioning.tasks"
_RUN_RENEWALS = "apps.commissioning.services.renewal.run_renewals"
_GET_SETTINGS = "apps.shared.tenants.models.TenantSettings.get_current_settings"
_NOTIFY = f"{_TASKS}._notify_office_of_renewal_failures"


def _settings(*, auto_renew: bool, min_weeks: int = 6) -> Mock:
    return Mock(
        subscriptions_are_auto_renewed=auto_renew,
        min_weeks_to_cancel_before_ending=min_weeks,
    )


def _run_task():
    from apps.commissioning.tasks import daily_subscription_renewals

    daily_subscription_renewals.call_local()


class TestDailyRenewalTaskGate:
    def test_flag_off_does_not_run_renewals(self, tenant):
        with (
            patch(_GET_SETTINGS, return_value=_settings(auto_renew=False)),
            patch(_RUN_RENEWALS) as run_renewals,
            patch(_NOTIFY) as notify,
        ):
            _run_task()

        run_renewals.assert_not_called()
        notify.assert_not_called()

    def test_no_settings_does_not_run_renewals(self, tenant):
        with (
            patch(_GET_SETTINGS, return_value=None),
            patch(_RUN_RENEWALS) as run_renewals,
            patch(_NOTIFY) as notify,
        ):
            _run_task()

        run_renewals.assert_not_called()
        notify.assert_not_called()

    def test_flag_on_runs_renewals_with_configured_notice_period(self, tenant):
        with (
            patch(_GET_SETTINGS, return_value=_settings(auto_renew=True, min_weeks=8)),
            patch(_RUN_RENEWALS, return_value={"created": 3, "failed": []}) as renew,
            patch(_NOTIFY) as notify,
        ):
            _run_task()

        assert renew.called
        # The tenant's ``min_weeks_to_cancel_before_ending`` is threaded through
        # as the notice period (2nd positional arg) — a wrong-field read would
        # break this. (test_pytest is the only tenant, but assert on every call
        # so a multi-tenant session stays honest.)
        for call in renew.call_args_list:
            assert call.args[1] == 8
        # No failures → no digest email.
        notify.assert_not_called()

    def test_failures_are_emailed_to_the_office(self, tenant):
        failed = [{"id": "s1", "label": "1", "reason": "no_variation"}]
        with (
            patch(_GET_SETTINGS, return_value=_settings(auto_renew=True)),
            patch(_RUN_RENEWALS, return_value={"created": 0, "failed": failed}),
            patch(_NOTIFY) as notify,
        ):
            _run_task()

        assert notify.called
        # The failure list is handed to the digest helper verbatim.
        assert notify.call_args.args[1] == failed

    def test_run_date_is_today(self, tenant):
        with (
            patch(_GET_SETTINGS, return_value=_settings(auto_renew=True)),
            patch(_RUN_RENEWALS, return_value={"created": 0, "failed": []}) as renew,
            patch(_NOTIFY),
        ):
            from django.utils import timezone

            _run_task()

        assert renew.called
        assert renew.call_args.args[0] == timezone.localdate()
        assert isinstance(renew.call_args.args[0], datetime.date)
