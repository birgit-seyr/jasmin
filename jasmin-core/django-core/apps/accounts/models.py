import logging
import uuid
from typing import Any

from django.conf import settings
from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models
from django.db.models import F, Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from nanoid import generate

from apps.authz.roles import VALID_ROLES, Role
from apps.shared.languages import LanguageChoices

from .constants import ID_LENGTH, JASMIN_ID_ALPHABET

logger = logging.getLogger(__name__)


def generate_jasmin_id() -> str:
    return generate(alphabet=JASMIN_ID_ALPHABET, size=ID_LENGTH)


def _clean_role_list(roles) -> tuple[list[str], list[str]]:
    """Split ``roles`` into ``(known, unknown)``, de-duplicated, order kept.

    A non-sequence yields nothing known. That guard is load-bearing rather
    than defensive: every membership test here is ``in``-based, so a bare
    string would be matched a character at a time — ``roles="superadmin"``
    would satisfy a check for ``"admin"``.
    """
    if not isinstance(roles, (list, tuple, set, frozenset)):
        return [], []
    known: list[str] = []
    unknown: list[str] = []
    for role in roles:
        bucket = known if role in VALID_ROLES else unknown
        if role not in bucket:
            bucket.append(role)
    return known, unknown


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
        (which could swallow other unique-constraint failures that happen to
        mention the word "id").
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
    def get_queryset(self):
        """Join the profile on every user query.

        ``roles`` lives on the profile, and every permission check reads it —
        several times per request. Without this join each of those is a second
        SELECT. Doing it in the default manager rather than in an
        authentication subclass also covers SimpleJWT, which loads the request
        user through ``UserModel._default_manager`` and would otherwise need a
        version-coupled override.
        """
        return super().get_queryset().select_related("jasmin_profile")

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
    # Superseded by ``JasminProfile.roles``, which the ``roles`` property
    # reads. Kept as a mirrored copy, written on every role change, so a
    # release can be reverted without restoring a backup — migrations are
    # forward-only, so this column is the only cheap way back. Nothing reads
    # it; the follow-up migration that drops it is the end of the move.
    #
    # ``db_column`` pins the physical name: a Django model cannot carry a
    # field and a property of the same name (whichever is declared second
    # silently wins), so the attribute had to be renamed while the column
    # stayed put.
    legacy_roles = models.JSONField(
        default=list, blank=True, null=True, db_column="roles"
    )

    date_joined = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_login_ip = models.GenericIPAddressField(blank=True, null=True)

    # Server-side session cut-off: any refresh token minted before this instant
    # is rejected by ``refresh_access_token``. Stamped on password
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
        _known, invalid = _clean_role_list(self.roles)
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

        # ``roles`` is a property, not a column: Django validates
        # ``update_fields`` against concrete fields and would raise. Callers
        # legitimately name it to mean "persist the roles", so translate
        # rather than refuse — the flush below is what actually writes them.
        requested = kwargs.get("update_fields")
        if requested is not None and "roles" in requested:
            kwargs["update_fields"] = [f for f in requested if f != "roles"]

        # Only normalise when roles were actually assigned on this instance.
        # Reading them unconditionally would put a profile query on all ~20
        # user.save() paths that have nothing to do with roles.
        pending_roles = self._normalised_role_buffer()
        if pending_roles is not None:
            self._roles_buffer = pending_roles
            # Mirror into the retained column in the same UPDATE.
            self.legacy_roles = pending_roles

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
            if pending_roles is not None:
                extra.add("legacy_roles")
            if "account_status" in update_fields:
                extra.update(stamped)
            kwargs["update_fields"] = list({*update_fields, *extra})

        was_insert = self._state.adding
        super().save(*args, **kwargs)

        # After the user row exists, so the profile's FK has something to
        # point at. Every user gets a profile, whether or not roles were
        # assigned — a user without one would read as role-less.
        if pending_roles is not None or was_insert:
            self._flush_roles(pending_roles or [], kwargs.get("using"))

    # ------------------------------------------------------------------ #
    # Roles                                                               #
    # ------------------------------------------------------------------ #

    # A pending role write, held only between assignment and the next save.
    # Annotated without a value on purpose: its ABSENCE is what distinguishes
    # "roles were never touched on this instance" from a deliberate
    # ``user.roles = []``, which is a real operation that must reach the row.
    _roles_buffer: Any

    @property
    def roles(self) -> list[str]:
        """The user's role list, stored on the linked :class:`JasminProfile`.

        A property rather than a column so a host project embedding Jasmin can
        supply its own ``AUTH_USER_MODEL``: Jasmin cannot add columns to a user
        model it does not own, but it can carry a profile beside it.
        """
        try:
            return self._roles_buffer
        except AttributeError:
            pass
        if self._state.adding:
            # The nanoid default means ``pk`` is already populated before the
            # first save, so a relation read here would query for a profile
            # row that cannot exist yet.
            return []
        try:
            return self.jasmin_profile.roles or []
        except JasminProfile.DoesNotExist:
            # Fail closed, but never silently: every permission class reads
            # this list, so a missing profile would otherwise read as
            # "no roles" and deny access with no trace of why.
            # ``save()`` creates the row for every new user and the backfill
            # covered the existing ones, so reaching this is a defect.
            logger.error("jasmin_user.profile_missing user=%s", self.pk)
            return []

    @roles.setter
    def roles(self, value) -> None:
        # Buffered rather than written through: the setter has to work on an
        # unsaved instance (``JasminUser(roles=[...])``, which every factory
        # and the ``create_user`` funnel rely on), where there is no row to
        # write to yet. ``save()`` flushes it.
        self._roles_buffer = value

    def refresh_from_db(self, using=None, fields=None, from_queryset=None) -> None:
        # Django clears the cached reverse one-to-one, but knows nothing about
        # the buffer — leaving it in place would keep serving a value the
        # caller asked to re-read from the database.
        self.__dict__.pop("_roles_buffer", None)
        super().refresh_from_db(using=using, fields=fields, from_queryset=from_queryset)

    def _normalised_role_buffer(self) -> list[str] | None:
        """The pending role write, cleaned — or None when roles weren't touched.

        Drop-and-log rather than raise: a row that already holds an illegal
        value has to stay saveable, or nobody — including an admin trying to
        fix the roles — could write to it at all.
        """
        try:
            buffered = self._roles_buffer
        except AttributeError:
            return None
        known, unknown = _clean_role_list(buffered)
        if unknown:
            logger.warning(
                "jasmin_user.unknown_roles_dropped user=%s dropped=%s",
                self.pk,
                sorted(unknown),
            )
        return known

    def _flush_roles(self, roles: list[str], using: str | None) -> None:
        """Persist the pending role write to the profile, creating it if needed."""
        JasminProfile.objects.using(using).update_or_create(
            user_id=self.pk, defaults={"roles": roles}
        )
        self.__dict__.pop("_roles_buffer", None)
        # Drop the stale cached relation so the next read re-queries.
        self._state.fields_cache.pop("jasmin_profile", None)

    # ------------------------------------------------------------------ #
    # Convenience accessors                                               #
    # ------------------------------------------------------------------ #

    @property
    def name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def get_full_name(self) -> str:
        return self.name

    def has_any_role(self, roles) -> bool:
        # ``save()`` normalises, but an unsaved instance can hold anything, and
        # a bare string would turn this into a substring test — see
        # ``_clean_role_list``.
        own = self.roles if isinstance(self.roles, (list, tuple)) else []
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
        """Validate, de-duplicate, assign.

        Raises on an unknown role, unlike ``save()`` which drops and logs: a
        caller reaching for this method is stating the roles explicitly, so a
        typo should be refused rather than quietly discarded.
        """
        known, invalid = _clean_role_list(roles)
        if invalid:
            raise ValidationError(
                "Invalid role(s): %(invalid)s",
                code="invalid_roles",
                params={"invalid": ", ".join(invalid)},
            )
        self.roles = known


class JasminProfile(models.Model):
    """Jasmin's own per-user state, held beside the user model rather than on it.

    Jasmin is meant to be embeddable as a package in a host Django project that
    owns ``AUTH_USER_MODEL``. Such a host cannot be asked to add Jasmin's
    columns to its user table, so anything Jasmin needs about a user beyond
    Django's own auth fields belongs here.

    Reached through ``JasminUser.roles``; there is no reason to query it
    directly outside this module.
    """

    # The profile has no identity of its own — it is the user's Jasmin state —
    # so it borrows the user's primary key instead of carrying a second,
    # meaningless nanoid. This is a deliberate departure from ``JasminModel``,
    # which every other tenant model subclasses.
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="jasmin_profile",
        primary_key=True,
    )
    roles = models.JSONField(
        default=list, blank=True, null=True, help_text="List of roles this user has"
    )

    def __str__(self) -> str:
        return f"JasminProfile({self.user_id})"
