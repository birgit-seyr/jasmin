"""Rewrite stored billing-profile IBANs into their canonical form.

Every IBAN write stores the canonical form (``normalized_iban``: no whitespace,
upper-case), because the pain.008 debtor block only strips spaces and the XSD
refuses a lower-case IBAN, which aborts the whole batch. This brings rows
written in another form up to it. Idempotent: a canonical IBAN is left alone,
so a second run changes nothing.

An IBAN that is not valid even in its canonical form is never touched — it is
reported by member number, and the office corrects it. The report never prints
the IBAN itself.

Each fix is saved through the model, so it passes the model's validation and
is recorded in the audit log (with the IBAN masked).

Usage:
    python manage.py normalize_ibans --dry-run                 # all tenants
    python manage.py normalize_ibans                           # all tenants
    python manage.py normalize_ibans --tenant <schema>         # one tenant
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django_tenants.utils import schema_context

from apps.payments.models import BillingProfile
from apps.payments.serializers import normalized_iban
from apps.shared.iban_validator import validate_iban as validate_iban_format
from apps.shared.tenants.models import Tenant


@dataclass
class _TenantOutcome:
    normalised: int = 0
    invalid: list[str] = field(default_factory=list)
    unsaveable: list[str] = field(default_factory=list)


def _is_valid_iban(iban: str) -> bool:
    try:
        validate_iban_format(iban)
    except DjangoValidationError:
        return False
    return True


def _member_label(profile: BillingProfile) -> str:
    return f"member {profile.member.member_number} (profile {profile.pk})"


def _normalise_tenant(*, dry_run: bool) -> _TenantOutcome:
    outcome = _TenantOutcome()
    # The column is encrypted at rest, so the comparison has to run on the
    # decrypted values the model hands back, not in SQL.
    profiles = BillingProfile.objects.select_related("member").order_by("pk")
    for profile in profiles.iterator(chunk_size=500):
        if not profile.iban:
            continue
        canonical = normalized_iban(profile.iban)
        if not _is_valid_iban(canonical):
            outcome.invalid.append(_member_label(profile))
            continue
        if canonical == profile.iban:
            continue
        if dry_run:
            outcome.normalised += 1
            continue
        profile.iban = canonical
        try:
            with transaction.atomic():
                profile.save(update_fields=["iban"])
        except DjangoValidationError as exc:
            # ``save()`` runs ``full_clean()``, which can refuse a row for a
            # reason other than its IBAN (an active SEPA profile missing its
            # account holder). That row stays as it was, and is reported.
            outcome.unsaveable.append(
                f"{_member_label(profile)}: {', '.join(sorted(exc.message_dict))}"
            )
            continue
        outcome.normalised += 1
    return outcome


class Command(BaseCommand):
    help = (
        "Rewrite billing-profile IBANs into their canonical form (no whitespace, "
        "upper-case); report the ones that are not valid IBANs."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--tenant",
            help="Limit to one tenant (schema_name). Default: all active tenants.",
            default=None,
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without saving anything.",
        )

    def handle(self, *args, **options):
        tenant_schema = options.get("tenant")
        dry_run = options["dry_run"]
        if tenant_schema:
            tenants = Tenant.objects.filter(schema_name=tenant_schema)
            if not tenants.exists():
                raise CommandError(f"No tenant with schema '{tenant_schema}'.")
        else:
            tenants = Tenant.objects.filter(is_active=True).exclude(
                schema_name="public"
            )

        for tenant in tenants:
            with schema_context(tenant.schema_name):
                outcome = _normalise_tenant(dry_run=dry_run)
            self._report(tenant.schema_name, outcome, dry_run=dry_run)

    def _report(self, schema: str, outcome: _TenantOutcome, *, dry_run: bool) -> None:
        verb = "to normalise" if dry_run else "normalised"
        summary = (
            f"Tenant {schema}: {outcome.normalised} {verb}, "
            f"{len(outcome.invalid)} invalid"
        )
        if outcome.unsaveable:
            summary += f", {len(outcome.unsaveable)} could not be saved"
        self.stdout.write(self.style.SUCCESS(summary))
        for label in outcome.invalid:
            self.stdout.write(
                self.style.WARNING(
                    f"  invalid IBAN, left unchanged — the office must correct "
                    f"it: {label}"
                )
            )
        for label in outcome.unsaveable:
            self.stdout.write(
                self.style.WARNING(f"  not saved, refused by validation: {label}")
            )
