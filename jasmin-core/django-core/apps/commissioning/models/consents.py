"""Consent versioning — the *what*, *when*, and *by whom* of every
agreement a member made.

DSGVO Art. 7(1) requires the controller to be able to *demonstrate*
that consent was given. A timestamp on its own doesn't prove that —
you also need to show the exact text the member agreed to.

Two tables solve this:

  - ``ConsentDocument`` is append-only. Each policy/text revision
    creates a new row; old rows are never edited. The body is stored
    verbatim, plus a SHA-256 so the body's integrity is verifiable
    later even if someone edits the row by mistake. Validity is
    tracked by ``TimeBoundMixin`` (``valid_from`` / ``valid_until``),
    so the "what is the active privacy policy right now?" query is
    ``ConsentDocument.current.filter(kind="privacy")`` — same shape
    as every other time-bound config in the platform.

  - ``ConsentRecord`` is the *event*: this member agreed to that
    document at this moment, from this IP. Revocation (Art. 7(3))
    sets ``revoked_at`` rather than deleting the row — the audit
    trail must include the decision to revoke, not vanish it.

The denormalised cache columns on ``Member`` (``sepa_consent``,
``privacy_consent``, ``withdrawal_consent``) are kept and maintained
by ``ConsentService`` — they're the hot path for "is this member
currently consented?" without joining ConsentRecord on every page.
"""

from __future__ import annotations

import hashlib

from django.db import models
from django.utils import timezone

from .base import JasminModel
from .choices_text import ConsentKind
from .mixin import (
    TimeBoundMixin,
    nullable_date_order_constraint,
    time_bound_valid_range_constraint,
    validate_nullable_date_order,
)


def _sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ConsentDocument(JasminModel, TimeBoundMixin):
    """A specific revision of a legal document a member can consent to.

    Time-bound via ``TimeBoundMixin``:
      - ``valid_from`` — when this version starts being shown to members.
      - ``valid_until`` — auto-set when a successor is created (the
        mixin's ``handle_succession`` closes the previous active row
        in the same overlap group on ``valid_from - 1``).

    Overlap group: ``(kind, locale)``. At most one ConsentDocument per
    kind+locale combination may be active at any given moment.

    Append-only by convention — never edit the ``body`` after rows
    reference it via ``ConsentRecord``. To publish a new policy,
    insert a new row with a bumped ``version`` and a future
    ``valid_from``.


    """

    overlap_unique_fields = ("kind", "locale")

    kind = models.CharField(max_length=40, choices=ConsentKind.choices)
    version = models.CharField(
        max_length=40,
        help_text="Stable identifier. ISO date like '2026-05-20' or "
        "semver-style '3.1' both work; pick one convention per tenant.",
    )
    locale = models.CharField(max_length=10, default="de")
    title = models.CharField(max_length=200, blank=True, default="")
    body = models.TextField(
        help_text="Verbatim text shown to the member. Markdown or HTML "
        "depending on tenant convention — store it as-shown."
    )
    body_sha256 = models.CharField(
        max_length=64,
        editable=False,
        help_text="Computed on save. Lets us detect post-hoc edits to "
        "``body`` even though by policy they shouldn't happen.",
    )
    # Immutable rendered PDF of this version, generated ONCE from the (append-
    # only) ``body`` via WeasyPrint — a byte-stable legal artifact for download.
    # Rendered eagerly on create and lazily on first download (ensure_pdf), so
    # every version gets one without a separate backfill.
    pdf = models.FileField(
        upload_to="consent_documents/",
        blank=True,
        null=True,
        editable=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["kind", "version", "locale"],
                name="consentdocument_unique_kind_version_locale",
            ),
            time_bound_valid_range_constraint("consentdocument_valid_range"),
        ]
        ordering = ["kind", "locale", "-valid_from"]

    def __str__(self) -> str:
        return f"{self.kind}/{self.version}/{self.locale}"

    def clean(self) -> None:
        """Skip the Monday-only check on ``valid_from``.

        ``TimeBoundMixin``'s default ``validate_week_boundaries``
        enforces Monday-only ``valid_from`` because most time-bound
        models in the platform align with the weekly share cycle.
        Consent documents don't: a privacy-policy revision goes live
        the moment legal review finishes, on whatever calendar day
        that lands on. The ``valid_from`` is a calendar marker, not
        a share-week boundary.

        We still enforce ``validate_date_range`` (valid_until cannot
        precede valid_from) and the overlap-group uniqueness check —
        those invariants matter regardless of the weekday rule.
        """
        # Re-implement the parent's clean() minus the Monday call,
        # by skipping TimeBoundMixin in the MRO.
        super(TimeBoundMixin, self).clean()
        self.validate_date_range(self.valid_from, self.valid_until)
        if self.overlap_unique_fields:
            self._validate_no_overlap()

    def save(self, *args, **kwargs):
        # Recompute the hash on every save so the row is always
        # self-consistent. Once a ConsentRecord points here you
        # shouldn't be calling .save() at all, but if it happens the
        # hash stays truthful and any tampering is detectable.
        self.body_sha256 = _sha256_of(self.body or "")
        super().save(*args, **kwargs)

    @property
    def pdf_filename(self) -> str:
        """Download filename, named by the human title (not the kind), e.g.
        ``coop-share-contract_3.1.pdf``. Falls back to the kind only if a
        document genuinely has no title."""
        from django.utils.text import slugify

        base = slugify(self.title) or self.kind
        return f"{base}_{self.version}.pdf"

    def ensure_pdf(self):
        """Render + store the PDF once (idempotent); return the FieldFile.

        Generated from the immutable ``body`` on first need — eagerly at
        creation and lazily on first download — so every version has a
        byte-stable PDF without a separate backfill step. A no-op (returns the
        stored file) once rendered.
        """
        if self.pdf:
            return self.pdf
        from apps.commissioning.services.consent_pdf import render_consent_pdf

        content = render_consent_pdf(self)
        self.pdf.save(self.pdf_filename, content, save=True)
        return self.pdf


class ConsentRecord(JasminModel):
    """One member's act of consenting to one ``ConsentDocument`` at
    one moment in time, plus an optional revocation tail.

    ``on_delete=PROTECT`` everywhere: neither the member nor the
    document may disappear underneath the audit trail. If a member
    is anonymised (DSGVO Art. 17 / our retention policy), nullify the
    PII fields on Member but keep the ConsentRecord row.
    """

    member = models.ForeignKey(
        "commissioning.Member",
        on_delete=models.PROTECT,
        related_name="consents",
    )
    document = models.ForeignKey(
        ConsentDocument,
        on_delete=models.PROTECT,
        related_name="records",
    )
    consented_at = models.DateTimeField(default=timezone.now)

    # Captured for forensic value if the consent is ever challenged.
    # Both optional — staff entering a paper-signed consent on behalf
    # of an offline member won't have an IP/UA to record.
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.CharField(max_length=500, blank=True, default="")

    # Revocation is a state transition, not a delete. Once set, the
    # consent stops counting toward the denormalised cache on Member.
    revoked_at = models.DateTimeField(blank=True, null=True)
    revoked_reason = models.CharField(max_length=200, blank=True, default="")
    revoked_by = models.ForeignKey(
        "accounts.JasminUser",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="+",
        help_text="Office staff revoking on the member's behalf, OR the "
        "member themselves via the self-service portal.",
    )

    class Meta:
        ordering = ["-consented_at"]
        indexes = [
            # Hot path: "latest unrevoked consent for member X, kind Y"
            # used by ConsentService to refresh the Member cache.
            models.Index(fields=["member", "-consented_at"]),
        ]
        constraints = [
            # A consent cannot be revoked before it was given. Both fields are
            # DateTimeFields. NULL-tolerant: only enforced when both are set
            # (``revoked_at`` NULL means "still active").
            nullable_date_order_constraint(
                "revoked_at",
                "consented_at",
                name="consentrecord_revoked_after_consented",
            ),
        ]

    def __str__(self) -> str:
        state = "revoked" if self.revoked_at else "active"
        return f"{self.member_id} → {self.document_id} ({state})"

    def clean(self) -> None:
        super().clean()
        # A consent cannot be revoked before it was given. NULL-tolerant: only
        # enforced when both timestamps are set.
        validate_nullable_date_order(
            self,
            "revoked_at",
            "consented_at",
            message="Revocation date must be on or after the consent date.",
        )

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None
