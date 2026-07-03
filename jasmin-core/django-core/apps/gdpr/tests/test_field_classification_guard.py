"""Discovery guard for the field-classification map.

Walks every model in the four PII-bearing app labels (``accounts``,
``commissioning``, ``payments``, ``notifications``) and flags any
field whose **name** looks like PII (``email``, ``iban``, ``phone``,
``address``, …) but is NOT classified in
``apps.gdpr.field_classes.FIELD_CLASSIFICATION``.

The point: when a future PR adds, say, a ``passport_number`` column
on a Member, or an ``email_4`` on ContactEntity, this test fails at
PR time with a message naming the exact field. The PR author then
has to either:

  (a) add the field to ``FIELD_CLASSIFICATION`` (classifying it as
      PII_IMMEDIATE / PII_RETAINED / TOMBSTONE), OR
  (b) add it to :data:`IGNORE_FIELDS` below with a justification.

Both are conscious decisions; either is fine. What's NOT fine is
silently shipping a new PII column that ``anonymize_user`` doesn't
know about — which is exactly the bug pattern that motivated this
roadmap.

The ignore list is the documentation. Anything in it is a deliberate
choice ("this field NAME looks like PII but isn't / is intentionally
retained / is operational"). Read it like a code comment.
"""

from __future__ import annotations

from django.apps import apps

from apps.gdpr.field_classes import FIELD_CLASSIFICATION

# ---------------------------------------------------------------------------
# Tokens that, if they appear in a field name, raise a PII suspicion. Mix of
# substring tokens (``email`` catches ``email_2``, ``invoice_email``…) and
# exact-name tokens (``uid`` exact, because ``uuid`` shouldn't match).
# ---------------------------------------------------------------------------
PII_SUBSTRING_TOKENS = (
    "email",
    "iban",
    "phone",
    "address",
    "first_name",
    "last_name",
    "company_name",
    "pickup_name",
    "contact_name",
    "name_for_member_pages",
    "invoice_name",
    "account_owner",
    "account_holder",
    "sepa_mandate_reference",
    "ip_address",
    "last_login_ip",
    "user_agent",
    "city",
    "zip_code",
    "country",
    # Free-text cancellation reasons routinely hold PII — force every
    # ``cancellation_reason`` / ``cancelled_reason`` column to be classified or
    # explicitly ignored (GDPR-DEL-2). Exact-ish names, not a broad "reason", so
    # unrelated ``revoked_reason`` / ``correction_reason`` aren't dragged in.
    "cancellation_reason",
    "cancelled_reason",
    "acronym",
    "coords_lat",
    "coords_lon",
    "access_code",
)
PII_EXACT_TOKENS = (
    "username",
    "recipient",
    "bic",
    "uid",
    "avatar",
)

# Field names that ALWAYS indicate PII regardless of column type.
# Without this list the walker below skips date/integer/boolean
# columns entirely (to avoid e.g. ``capacity`` matching ``city``),
# which means PII dates like ``birth_date`` slip through silently —
# that's how DoB went unclassified in the 2026-06 GenG §30 audit.
# Add a new entry here whenever a field of a non-text type is
# personal data (e.g. a hypothetical ``passport_expiry: DateField``).
PII_NAMES_ANY_TYPE = (
    "birth_date",
    "date_of_birth",
    "dob",
)


def _field_looks_like_pii(field_name: str) -> bool:
    if field_name in PII_EXACT_TOKENS:
        return True
    return any(token in field_name for token in PII_SUBSTRING_TOKENS)


# Field types whose value can carry textual PII. Booleans + numeric +
# date types are excluded so that:
#   - ``offer_via_email`` (Boolean: does this reseller want emails?)
#     doesn't get flagged on the substring "email".
#   - ``capacity`` (PositiveIntegerField) doesn't get flagged on the
#     "city" substring inside its name.
# Any text/email/IP field stays in scope. The encrypted variants
# (``EncryptedCharField`` etc.) report as their base CharField type
# via ``get_internal_type``, so they're covered by "CharField".
PII_CAPABLE_FIELD_TYPES = frozenset(
    {
        "CharField",
        "TextField",
        "EmailField",
        "URLField",
        "GenericIPAddressField",
        "ImageField",
        "FileField",
        "SlugField",
    }
)


# ---------------------------------------------------------------------------
# Explicit allow-list of "field name looks PII but is intentionally not
# classified for anonymization". Each entry needs a one-line justification —
# this dict is the audit trail for any future "why isn't X scrubbed?" question.
# Format: {(model_label, field_name): "reason"}
# ---------------------------------------------------------------------------
IGNORE_FIELDS: dict[tuple[str, str], str] = {
    # DeletionLog is the audit trail of GDPR requests. Storing the
    # original email is the entire point — without it, restore-replay
    # can't find the row to re-anonymize after a backup restore.
    ("gdpr.DeletionLog", "user_email"): (
        "Audit trail of the deletion event itself; required for "
        "restore-replay (apps/gdpr/management/commands/replay_gdpr_deletions.py)."
    ),
    # DeletionRequest IS the audit row of the deletion request itself;
    # its PII-shaped columns are the audit fields — scrubbing them
    # would defeat the point of the row. Same reasoning as
    # ``DeletionLog.user_email`` above.
    ("gdpr.DeletionRequest", "requested_email"): (
        "Snapshot of the requester's email at request time — the "
        "audit trail's whole purpose is to preserve who asked, when."
    ),
    ("gdpr.DeletionRequest", "email_confirmed_ip"): (
        "IP that clicked the confirmation link — kept as forensic "
        "evidence that the deletion was confirmed from a real device."
    ),
    # DeliveryStation is shared infrastructure (a pickup point used
    # by many members). contact_name / contact_phone / access_code
    # belong to the STATION, not to any single data subject — they're
    # B2B operational data (e.g. "key in the lockbox, code 4711",
    # "call Maria at the bakery"). Not deleted with any one member.
    ("commissioning.DeliveryStation", "contact_name"): (
        "Belongs to the pickup point, not to any single member. "
        "Shared infrastructure — no single data subject."
    ),
    ("commissioning.DeliveryStation", "contact_phone"): (
        "Belongs to the pickup point, not to any single member. "
        "Shared infrastructure — no single data subject."
    ),
    ("commissioning.DeliveryStation", "access_code"): (
        "Door / lockbox code for the pickup point. Not personal data."
    ),
    # SharesDeliveryDay / OrdersDeliveryDay use ``acronym`` as a
    # short route code (e.g. "MO", "DI") in delivery planning. Not
    # a person's name acronym.
    ("commissioning.SharesDeliveryDay", "acronym"): (
        "Route code abbreviation (e.g. 'MO' for Montag), not personal data."
    ),
    ("commissioning.OrdersDeliveryDay", "acronym"): (
        "Route code abbreviation (e.g. 'MO' for Montag), not personal data."
    ),
}


def _gather_pii_field_violations() -> list[str]:
    """Return a list of human-readable violation messages — empty
    when every PII-named field is either classified or ignored."""
    violations: list[str] = []
    for app_label in ("accounts", "commissioning", "payments", "notifications"):
        app_config = apps.get_app_config(app_label)
        for model in app_config.get_models():
            model_label = model._meta.label  # "app.ModelName"
            classified = FIELD_CLASSIFICATION.get(model_label, {})
            for field in model._meta.get_fields():
                # Skip reverse relations and m2m through-rows: we
                # only care about concrete columns on this table.
                if not getattr(field, "concrete", False):
                    continue
                if field.many_to_many:
                    continue
                field_name = field.name
                # Two-pass check:
                #   1. Fields named on the explicit ``PII_NAMES_ANY_TYPE``
                #      list are PII regardless of column type (catches
                #      date-typed PII like ``birth_date``).
                #   2. Everything else is only suspected when both the
                #      type is text-capable AND the name matches a PII
                #      token — avoids false positives like ``capacity``
                #      (PositiveIntegerField) matching the ``city``
                #      substring or ``offer_via_email`` (Boolean)
                #      matching ``email``.
                if field_name not in PII_NAMES_ANY_TYPE:
                    if field.get_internal_type() not in PII_CAPABLE_FIELD_TYPES:
                        continue
                    if not _field_looks_like_pii(field_name):
                        continue
                if field_name in classified:
                    continue
                if (model_label, field_name) in IGNORE_FIELDS:
                    continue
                violations.append(f"  - {model_label}.{field_name}")
    return violations


def test_every_pii_named_field_is_classified_or_ignored():
    """Each model field whose name suggests PII must be either in
    ``FIELD_CLASSIFICATION`` (so ``anonymize_user`` knows what to do
    with it) or in :data:`IGNORE_FIELDS` (with a one-line reason
    explaining why it isn't PII / isn't tied to a data subject).

    If this test fails on a field you just added: pick a
    ``FieldClass`` for it (PII_IMMEDIATE, PII_RETAINED, TOMBSTONE)
    and add the row to ``apps/gdpr/field_classes.py`` — or, if the
    field name only LOOKS like PII but isn't, add an entry to
    ``IGNORE_FIELDS`` with the reason.
    """
    violations = _gather_pii_field_violations()
    assert not violations, (
        "The following model fields have PII-suggesting names but are "
        "neither classified in FIELD_CLASSIFICATION nor in the IGNORE_FIELDS "
        "allow-list. Add each to one or the other (see docstring of "
        "apps/gdpr/tests/test_field_classification_guard.py for guidance):\n"
        + "\n".join(violations)
    )


def test_ignored_fields_still_exist_on_their_model():
    """Guard against IGNORE_FIELDS drift. If a model is renamed or
    a field is dropped, the IGNORE entry becomes a lie — bin it
    rather than letting the allow-list grow stale."""
    stale: list[str] = []
    for (model_label, field_name), _reason in IGNORE_FIELDS.items():
        try:
            model = apps.get_model(model_label)
        except LookupError:
            stale.append(f"  - {model_label} (model no longer exists)")
            continue
        field_names = {f.name for f in model._meta.get_fields()}
        if field_name not in field_names:
            stale.append(f"  - {model_label}.{field_name} (field no longer exists)")
    assert not stale, (
        "IGNORE_FIELDS in apps/gdpr/tests/test_field_classification_guard.py "
        "references model fields that no longer exist. Remove the stale "
        "entries:\n" + "\n".join(stale)
    )


def test_guard_catches_date_typed_pii_when_unclassified(monkeypatch):
    """Self-check on the guard's own logic.

    The 2026-06 ``birth_date`` regression slipped past the original
    text-only walker because ``DateField`` isn't in
    ``PII_CAPABLE_FIELD_TYPES``. The fix was to add
    ``PII_NAMES_ANY_TYPE`` and a two-pass check.

    Lock that behaviour: temporarily drop ``birth_date`` from the
    classification map; assert the walker raises a violation naming
    that exact field. Without this self-check, a future refactor
    could disable the date-aware pass and the next ``DateField``
    PII column would silently survive anonymisation.
    """
    # Strip birth_date from the live classification dict for the
    # duration of this test. monkeypatch restores it on teardown.
    cloned = dict(FIELD_CLASSIFICATION["commissioning.Member"])
    cloned.pop("birth_date", None)
    monkeypatch.setitem(FIELD_CLASSIFICATION, "commissioning.Member", cloned)

    violations = _gather_pii_field_violations()
    assert any("commissioning.Member.birth_date" in v for v in violations), (
        "Date-typed PII regression: classification guard didn't flag "
        "an unclassified ``birth_date``. Either the PII_NAMES_ANY_TYPE "
        "check was reverted or the two-pass walker logic in "
        "_gather_pii_field_violations was rewritten incorrectly."
    )


def test_classified_fields_still_exist_on_their_model():
    """Mirror of the above for FIELD_CLASSIFICATION: every (model,
    field) entry must still resolve to a real field. Otherwise the
    classification is dead code that could mask a regression (a
    field gets renamed; the OLD entry stays; the NEW name has no
    classification → silent leak)."""
    stale: list[str] = []
    for model_label, fields in FIELD_CLASSIFICATION.items():
        try:
            model = apps.get_model(model_label)
        except LookupError:
            stale.append(f"  - {model_label} (model no longer exists)")
            continue
        field_names = {f.name for f in model._meta.get_fields()}
        for field_name in fields:
            if field_name not in field_names:
                stale.append(f"  - {model_label}.{field_name} (field no longer exists)")
    assert not stale, (
        "FIELD_CLASSIFICATION in apps/gdpr/field_classes.py references "
        "fields that no longer exist on their model. Remove the stale "
        "entries (or rename them to match the new field name):\n" + "\n".join(stale)
    )
