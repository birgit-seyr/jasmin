import uuid

from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from nanoid import generate

from apps.authz.roles import VALID_ROLES, Role
from apps.shared.languages import LanguageChoices

from .constants import ID_LENGTH


def generate_jasmin_id():
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    return generate(alphabet=alphabet, size=ID_LENGTH)


class JasminModel(models.Model):
    id = models.CharField(
        "ID",
        max_length=ID_LENGTH,
        unique=True,
        primary_key=True,
        default=generate_jasmin_id,
    )

    class Meta:
        abstract = True


# =========================================================================== #
# Account-status state machine                                                 #
#                                                                              #
# - "pending_invitation": user provisioned by an admin invitation; password    #
#   not set yet. Cannot log in until they accept and set a password.           #
# - "pending_approval":   user self-registered (always with a Member row);     #
#   password is set but admin has not yet confirmed the linked Member. Cannot  #
#   log in until office confirms the member.                                   #
# - "active":             allowed to log in.                                   #
# - "inactive":           blocked. Reachable only via admin action.            #
#                                                                              #
# `is_active` is DERIVED from `account_status` in `JasminUser.save()`. Never    #
# set it by hand.                                                              #
# =========================================================================== #
ACCOUNT_STATUS_CHOICES = [
    ("active", "Active"),
    ("pending_approval", "Pending Admin Approval"),
    ("pending_invitation", "Pending Invitation"),
    ("inactive", "Inactive"),
]


class JasminUserManager(BaseUserManager):
    def create_user(self, first_name, last_name, email, password=None, **kwargs):
        if first_name is None:
            raise TypeError(_("Users must have a first name."))
        if last_name is None:
            raise TypeError(_("Users must have a last name."))
        if email is None:
            raise TypeError(_("Users must have an email address."))
        if password is None:
            raise TypeError("User must have a password.")

        kwargs["first_name"] = first_name
        kwargs["last_name"] = last_name
        kwargs["email"] = self.normalize_email(email)
        kwargs.setdefault("username", kwargs["email"].lower())

        user = self.model(**kwargs)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, first_name, last_name, email, password=None, **kwargs):
        kwargs.setdefault("account_status", "active")
        kwargs.setdefault("roles", [Role.ADMIN])
        user = self.create_user(first_name, last_name, email, password, **kwargs)
        user.is_superuser = True
        user.save(using=self._db)
        return user


class JasminUser(JasminModel, AbstractBaseUser, PermissionsMixin):
    """Custom user model. Each user exists globally per tenant schema."""

    public_id = models.UUIDField(
        db_index=True, unique=True, default=uuid.uuid4, editable=False
    )
    username = models.CharField(db_index=True, max_length=255, unique=True)

    first_name = models.CharField(max_length=255)
    last_name = models.CharField(max_length=255)
    email = models.EmailField(db_index=True, unique=True)
    avatar = models.ImageField(upload_to="avatars/", blank=True, null=True)

    account_status = models.CharField(
        max_length=20,
        choices=ACCOUNT_STATUS_CHOICES,
        default="pending_invitation",
    )
    # NOTE: derived from `account_status` in `save()`. Do not set by hand.
    # Kept as a separate column because Django auth, the admin site, password
    # reset views and SimpleJWT all read `is_active`.
    is_active = models.BooleanField(default=False)

    user_language = models.CharField(
        max_length=3,
        choices=LanguageChoices.choices,
        default=LanguageChoices.EN,
    )
    sidebar_collapsed = models.BooleanField(default=False)
    theme = models.CharField(
        max_length=10,
        choices=[("light", "Light"), ("dark", "Dark")],
        default="light",
    )
    edit_mode = models.CharField(
        max_length=10,
        choices=[("inline", "Inline Editing"), ("modal", "Modal Editing")],
        default="inline",
    )
    roles = models.JSONField(
        default=list, blank=True, null=True, help_text="List of roles this user has"
    )

    date_joined = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_login_ip = models.GenericIPAddressField(blank=True, null=True)

    # Server-side session cut-off: any refresh token minted before this instant
    # is rejected by ``refresh_access_token`` (GAP-1). Stamped on password
    # reset and "log out everywhere" so a stolen refresh token can't be
    # rotated forward indefinitely past a credential change. NULL = never
    # revoked. Robust against rotation (which mints new JTIs outside
    # ``OutstandingToken``); the token's ``iat`` is what's compared.
    sessions_revoked_at = models.DateTimeField(blank=True, null=True, editable=False)

    # Status-transition timestamps. Maintained by ``save()`` whenever
    # ``account_status`` flips. Both can be None for legacy rows that
    # existed before these columns were added.
    activated_at = models.DateTimeField(blank=True, null=True)
    inactivated_at = models.DateTimeField(blank=True, null=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    objects = JasminUserManager()

    class Meta:
        indexes = [
            models.Index(fields=["public_id"]),
            models.Index(fields=["email"]),
        ]
        constraints = [
            # A user can only be activated on/after they joined. NULL-tolerant:
            # a stamp that has never been set imposes no ordering.
            #
            # NOTE: there is intentionally NO inactivated_at >= activated_at
            # constraint. ``activated_at`` / ``inactivated_at`` track the *most
            # recent* activation and the *most recent* inactivation
            # independently. Re-activation (the allowed inactive -> active
            # transition) legitimately stamps a new ``activated_at`` that is
            # later than a prior ``inactivated_at``, so their relative order is
            # not an invariant.
            models.CheckConstraint(
                condition=(
                    Q(activated_at__isnull=True)
                    | Q(date_joined__isnull=True)
                    | Q(activated_at__gte=F("date_joined"))
                ),
                name="jasminuser_activated_after_joined",
            ),
        ]

    def __str__(self) -> str:
        return self.username

    # ------------------------------------------------------------------ #
    # Invariants                                                          #
    # ------------------------------------------------------------------ #

    def clean(self):
        super().clean()
        invalid = [r for r in (self.roles or []) if r not in VALID_ROLES]
        if invalid:
            raise ValidationError(
                {
                    "roles": ValidationError(
                        "Invalid role(s): %(invalid)s",
                        code="invalid_roles",
                        params={"invalid": ", ".join(invalid)},
                    )
                }
            )

        # Activation stamp must not predate the join date. NULL-tolerant: only
        # enforced when both ends of the pair are set.
        #
        # There is intentionally no inactivated_at-vs-activated_at check: those
        # two stamps track the most recent activation / inactivation
        # independently, and re-activation legitimately makes activated_at the
        # later of the two.
        if (
            self.activated_at is not None
            and self.date_joined is not None
            and self.activated_at < self.date_joined
        ):
            raise ValidationError(
                {
                    "activated_at": ValidationError(
                        "Activation cannot be before the join date.",
                        code="activated_before_joined",
                    )
                }
            )

    def save(self, *args, **kwargs):
        # Single source of truth: is_active is derived from account_status.
        self.is_active = self.account_status == "active"

        # Track status-transition timestamps. We only stamp the
        # ``activated_at`` / ``inactivated_at`` fields when the status
        # actually changes (or on the first save with a terminal status).
        update_fields = kwargs.get("update_fields")
        previous_status: str | None = None
        if self.pk is not None:
            previous_status = (
                type(self)
                .objects.filter(pk=self.pk)
                .values_list("account_status", flat=True)
                .first()
            )
        now = timezone.now()
        stamped: list[str] = []
        if self.account_status == "active" and previous_status != "active":
            self.activated_at = now
            stamped.append("activated_at")
        if self.account_status == "inactive" and previous_status != "inactive":
            self.inactivated_at = now
            stamped.append("inactivated_at")

        if update_fields is not None:
            extra = {"is_active"}
            if "account_status" in update_fields:
                extra.update(stamped)
            kwargs["update_fields"] = list({*update_fields, *extra})
        super().save(*args, **kwargs)

    # ------------------------------------------------------------------ #
    # Convenience accessors                                               #
    # ------------------------------------------------------------------ #

    @property
    def name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def get_full_name(self) -> str:
        return self.name

    def has_any_role(self, roles) -> bool:
        own = self.roles or []
        return any(r in own for r in roles)

    @property
    def is_staff(self) -> bool:
        """Required by Django admin."""
        return (
            self.has_any_role([Role.STAFF, Role.ADMIN, Role.MANAGEMENT, Role.OFFICE])
            or self.is_superuser
        )

    # ------------------------------------------------------------------ #
    # Role mutators                                                       #
    # ------------------------------------------------------------------ #

    def set_roles(self, roles) -> None:
        roles = list(roles or [])
        invalid = [r for r in roles if r not in VALID_ROLES]
        if invalid:
            raise ValidationError(
                "Invalid role(s): %(invalid)s",
                code="invalid_roles",
                params={"invalid": ", ".join(invalid)},
            )
        # de-dup, preserve order
        seen = set()
        deduped = []
        for r in roles:
            if r not in seen:
                seen.add(r)
                deduped.append(r)
        self.roles = deduped
