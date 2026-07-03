from __future__ import annotations

import datetime
from typing import Any

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.db import models
from django.utils import timezone


class SuperAdminManager(BaseUserManager):
    def create_user(
        self, email: str, password: str | None = None, **extra_fields: Any
    ) -> SuperAdmin:
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user


class SuperAdmin(AbstractBaseUser):
    """Super admin - only stored in public schema"""

    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=30, blank=True)
    last_name = models.CharField(max_length=30, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    is_staff = models.BooleanField(default=True)
    is_superuser = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = SuperAdminManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        db_table = "super_admin"

    def has_perm(self, perm: str, obj: Any = None) -> bool:
        return self.is_superuser


class SuperAdminBlacklistedToken(models.Model):
    """Public-schema blacklist for super-admin refresh tokens.

    We can't use rest_framework_simplejwt.token_blacklist here because that
    table has a FK to AUTH_USER_MODEL (= JasminUser, which lives in tenant
    schemas). Super-admin tokens are signed JWTs, so we only need to store
    the JTI and an expiry to revoke them.
    """

    jti = models.CharField(max_length=255, unique=True, db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    reason = models.CharField(max_length=64, blank=True, default="logout")

    class Meta:
        db_table = "super_admin_blacklisted_token"

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.jti} (until {self.expires_at:%Y-%m-%d %H:%M})"

    def has_module_perms(self, app_label: str) -> bool:
        return self.is_superuser


# ---------------------------------------------------------------------------
# Operational checklist (key rotations, restore drills, OS upgrades, etc.)
# ---------------------------------------------------------------------------
# Platform-wide ops items + an append-only completion log. Lives in the
# public schema alongside SuperAdmin because none of these items are
# tenant-scoped (rotating DJANGO_SECRET_KEY is one-per-platform, not
# one-per-tenant). A weekly Huey task surfaces overdue items to ops
# via ``mail_admins``.


class OpsChecklistItem(models.Model):
    """A recurring operational task you want to be reminded about.

    The ``runs`` related manager is an append-only completion history;
    treat it as the audit trail (nothing here deletes rows). Reminder
    cadence is ``interval_days`` after the most recent run, or after
    ``created_at`` if there's never been a run.
    """

    KIND_CHOICES = [
        ("rotate_django_secret", "Rotate DJANGO_SECRET_KEY"),
        ("rotate_field_encryption", "Rotate FIELD_ENCRYPTION_KEY"),
        ("rotate_db_password", "Rotate Postgres password"),
        ("rotate_bunny_token", "Rotate Bunny CDN API token"),
        ("rotate_email_creds", "Rotate email-provider credentials"),
        ("restore_drill", "Restore-from-backup drill"),
        ("postgres_security_upgrade", "Postgres security upgrade"),
        ("apt_upgrade", "OS apt upgrade"),
        ("user_account_review", "Review super-admin + admin accounts"),
        ("dependency_audit", "Manual dependency audit"),
        ("penetration_test", "External penetration test"),
        ("csp_audit", "CSP allowlist audit"),
        ("custom", "Custom"),
    ]

    kind = models.CharField(max_length=64, choices=KIND_CHOICES)
    title = models.CharField(max_length=200)
    description = models.TextField(
        blank=True,
        help_text=(
            "Runbook notes — what to actually do, where the keys live, "
            "links to relevant docs. Read by future-you at 02:00 during "
            "the next rotation, so be generous."
        ),
    )
    interval_days = models.PositiveIntegerField(
        help_text="Reminder fires this many days after the most recent run.",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ops_checklist_item"
        ordering = ["title"]

    def __str__(self) -> str:  # pragma: no cover
        return self.title

    @property
    def last_run(self) -> OpsChecklistRun | None:
        return self.runs.order_by("-completed_at").first()

    # ``*_for(last)`` take an already-resolved last run so a caller that
    # prefetched the runs (the list view) computes both without re-querying.
    # The properties below delegate, keeping the date math in one place.
    def next_due_at_for(self, last: OpsChecklistRun | None) -> datetime.datetime:
        anchor = last.completed_at if last is not None else self.created_at
        return anchor + datetime.timedelta(days=self.interval_days)

    def is_overdue_for(self, last: OpsChecklistRun | None) -> bool:
        return self.is_active and self.next_due_at_for(last) < timezone.now()

    @property
    def next_due_at(self) -> datetime.datetime:
        return self.next_due_at_for(self.last_run)

    @property
    def is_overdue(self) -> bool:
        return self.is_overdue_for(self.last_run)


class OpsChecklistRun(models.Model):
    """Append-only log: every time someone marks a checklist item done.

    Treat this table like ``auditlog_logentry`` — no updates, no
    deletes. The history IS the audit trail an auditor / DPO asks for.
    """

    item = models.ForeignKey(
        OpsChecklistItem,
        related_name="runs",
        on_delete=models.CASCADE,
    )
    completed_at = models.DateTimeField(default=timezone.now)
    completed_by = models.ForeignKey(
        "super_admin.SuperAdmin",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    notes = models.TextField(
        blank=True,
        help_text="Free-form: what changed, what was rotated, what worked.",
    )

    class Meta:
        db_table = "ops_checklist_run"
        ordering = ["-completed_at"]

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.item.title} @ {self.completed_at:%Y-%m-%d}"
