from django.core.management.base import BaseCommand
from django_tenants.utils import schema_context

from apps.accounts.models import JasminUser
from apps.gdpr.errors import RetentionPeriodActive
from apps.gdpr.models import DeletionLog
from apps.gdpr.services import GDPRService
from apps.shared.tenants.models import Tenant


class Command(BaseCommand):
    help = (
        "GDPR: After restoring a backup, replay deletion requests that were "
        "processed between the backup date and now. Iterates all tenant schemas."
    )

    def handle(self, *args, **options):
        tenants = Tenant.objects.exclude(schema_name="public")
        total_replayed = 0
        total_blocked = 0

        for tenant in tenants:
            with schema_context(tenant.schema_name):
                # Materialise: ``anonymize_user`` writes a fresh DeletionLog
                # per call, so iterate a fixed snapshot of the pre-restore logs.
                logs = list(DeletionLog.objects.all())
                for log in logs:
                    user = JasminUser.objects.filter(email=log.user_email).first()
                    if not (user and user.is_active):
                        # Already re-anonymized (email is now deleted_*@…) or
                        # gone — nothing to replay for this log.
                        continue
                    # The user came back from the backup with PII intact. Re-run
                    # the FULL anonymization (single source of truth: every
                    # per-model helper + FIELD_CLASSIFICATION + the "Gelöscht"
                    # tombstone) so EVERY PII surface is scrubbed again — not
                    # just the four JasminUser columns the old code touched.
                    try:
                        GDPRService.anonymize_user(user)
                    except RetentionPeriodActive:
                        # A restored statutory obligation (open CoopShare /
                        # invoice / charge) blocks re-anonymization. Skip this
                        # subject — don't abort the whole replay.
                        total_blocked += 1
                        self.stdout.write(
                            f"  [{tenant.schema_name}] SKIPPED {log.user_email}: "
                            "retention obligation active"
                        )
                        continue
                    total_replayed += 1
                    self.stdout.write(
                        f"  [{tenant.schema_name}] Re-anonymized user {log.user_email}"
                    )

        message = f"Done. Replayed {total_replayed} deletion(s)."
        if total_blocked:
            message += f" {total_blocked} skipped (retention obligation active)."
        self.stdout.write(self.style.SUCCESS(message))
