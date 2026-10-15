"""The pain.008 file a SEPA billing run exports: the document, and the
remittance text (``Ustrd``) each member sees on their bank statement."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

from django.utils import timezone
from sepaxml import SepaDD
from sepaxml.validation import ValidationError as SepaXmlValidationError

from core.tenant_db import connection

from .errors import SepaExportInvalid
from .serializers import normalized_iban

if TYPE_CHECKING:
    from apps.shared.tenants.models import Tenant

    from .models import BillingRun, ChargeSchedule

# Used when ``Tenant.sepa_remittance_template`` is blank. Friendly + compact:
# "<creditor> – <Month> <Year>" (e.g. "Marillenhof – Juni 2026") instead of the
# internal ``ChargeSchedule.description`` (share label + ISO date range).
# Plain hyphen (not en-dash) — the SEPA Latin charset excludes "–", and
# sepaxml's clean=True would silently downgrade it to "-" anyway.
DEFAULT_REMITTANCE_TEMPLATE = "{creditor} - {month}"

# de is the platform's primary locale and the members are German-speaking, so
# ``{month}`` renders German month names. Tenants wanting locale-neutral text
# can use ``{period}`` (numeric dates) instead.
_DE_MONTHS = (
    "",
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
)


def render_remittance(
    template: str, *, creditor: str, member: str, charge: ChargeSchedule
) -> str:
    """Render a tenant remittance template into the pain.008 ``Ustrd`` text
    of `charge`.

    Substitution is literal ``str.replace`` (NOT ``str.format``) so a stray
    brace or an unknown ``{placeholder}`` in operator-entered text can never
    raise — unknown tokens are simply left in place. Supported placeholders:
    ``{creditor}``, ``{member}``, ``{month}``, ``{period}``, ``{amount}``.
    Result is trimmed to the ISO 20022 140-char ``Ustrd`` limit.
    """
    start, end = charge.period_start, charge.period_end
    month = f"{_DE_MONTHS[start.month]} {start.year}"
    period = f"{start.strftime('%d.%m.%Y')}–{end.strftime('%d.%m.%Y')}"
    replacements = {
        "{creditor}": creditor,
        "{member}": member,
        "{month}": month,
        "{period}": period,
        "{amount}": f"{charge.expected_amount}",
    }
    text = template
    for token, value in replacements.items():
        text = text.replace(token, str(value))
    return text.strip()[:140]


def build_pain008_xml(run: BillingRun, charges: list[ChargeSchedule]) -> bytes:
    """Build a pain.008.001.02 SEPA Direct Debit XML for the run.

    Uses the ``sepaxml`` library so the generated document is
    schema-validated against the bundled XSD before it leaves the
    process — a malformed file can never reach the office. Missing
    creditor / debtor fields raise :class:`SepaExportInvalid`
    (a ``BadRequestError`` → HTTP 400 with the offending fields in
    ``details``).

    Rows are ordered ``(member_id, due_date, end_to_end_id)`` so
    the file is deterministic across re-runs of the same set of
    charges (locked by
    ``apps/payments/tests/test_billing_run_pain008.py``).
    """
    tenant = connection.tenant
    sepa = SepaDD(_creditor_config(tenant), schema="pain.008.001.02", clean=True)
    creditor_name = tenant.sepa_creditor_name.strip()

    # Operator-configurable bank-statement text (pain.008 ``Ustrd``). Blank
    # → a friendly default ("{creditor} – {month}"). Rendered per charge
    # below so each member sees readable text instead of the internal
    # ``ChargeSchedule.description`` (share label + ISO date range).
    remittance_template = (
        tenant.sepa_remittance_template.strip() or DEFAULT_REMITTANCE_TEMPLATE
    )

    ordered = sorted(
        charges,
        key=lambda charge: (
            charge.member_id,
            charge.due_date,
            charge.end_to_end_id or charge.pk,
        ),
    )
    # Mandates already assigned their single FRST in THIS file. SEPA
    # allows only one FRST per mandate, so a never-used mandate with
    # several charges in one run gets FRST on the first transaction and
    # RCUR on the rest (see the per-mandate sequence logic below).
    frst_assigned: set = set()
    today = timezone.localdate()
    for charge in ordered:
        billing_profile = getattr(charge.member, "billing_profile", None)
        if billing_profile is None:
            raise SepaExportInvalid(
                f"Charge {charge.pk}: member has no billing_profile; "
                "cannot include in SEPA XML.",
                details={"charge": str(charge.pk)},
            )
        mandate_ref = (billing_profile.sepa_mandate_reference or "").strip()
        mandate_signed = billing_profile.sepa_mandate_signed_at
        debtor_iban = normalized_iban(billing_profile.iban)
        debtor_name = billing_profile.account_holder.strip()
        if not (mandate_ref and mandate_signed and debtor_iban and debtor_name):
            raise SepaExportInvalid(
                f"Charge {charge.pk}: debtor missing mandate fields "
                "(mandate_reference, mandate_signed_at, IBAN, "
                "account_holder are all required).",
                details={"charge": str(charge.pk)},
            )

        # A mandate signed in the FUTURE (DtOfSgntr) is logically
        # invalid and some banks reject the batch. sepaxml only checks it is a
        # date instance, so guard it here before it reaches the file.
        if mandate_signed > today:
            raise SepaExportInvalid(
                f"Charge {charge.pk}: sepa_mandate_signed_at {mandate_signed} is in "
                "the future; a SEPA mandate cannot be dated after today.",
                details={
                    "charge": str(charge.pk),
                    "mandate_signed_at": str(mandate_signed),
                },
            )

        # pain.008 is EUR-only — the file's currency is hardcoded EUR above.
        # A charge stamped with a non-EUR currency (tenant.currency is a
        # free CharField) would otherwise be silently direct-debited as the
        # same numeric amount in EUR. Fail loudly instead of emitting a
        # wrong-currency debit.
        if charge.currency != "EUR":
            raise SepaExportInvalid(
                f"Charge {charge.pk}: currency {charge.currency} is not EUR; "
                "SEPA pain.008 is EUR-only.",
                details={"charge": str(charge.pk), "currency": charge.currency},
            )

        # FRST only for a mandate's very first-ever collection; RCUR
        # otherwise. ``sepa_mandate_first_use_at`` (stamped by
        # ``export()`` AFTER the file is built) covers PRIOR runs. But
        # within THIS file a never-used mandate can carry several charges
        # — only the first may be FRST, the rest must be RCUR, else the
        # bank rejects the batch for a duplicate FRST sequence.
        if billing_profile.sepa_mandate_first_use_at is not None:
            sequence_type = "RCUR"
        elif billing_profile.pk in frst_assigned:
            sequence_type = "RCUR"
        else:
            sequence_type = "FRST"
            frst_assigned.add(billing_profile.pk)

        sepa.add_payment(
            {
                "name": debtor_name[:70],  # ISO 20022 ``Nm`` max length
                "IBAN": debtor_iban,
                # ``amount`` is in CENTS (integer) per sepaxml's API.
                "amount": int(
                    (charge.expected_amount * 100).quantize(
                        Decimal("1"), rounding=ROUND_HALF_UP
                    )
                ),
                "type": sequence_type,
                # RequestedCollectionDate is the operator-set run
                # collection_date (when the bank debits), NOT each charge's
                # due_date. Per-charge due_dates would ignore the field's
                # documented purpose and (with batch=True) fragment the
                # file into one PmtInf per distinct due_date.
                "collection_date": run.collection_date,
                "mandate_id": mandate_ref,
                "mandate_date": mandate_signed,
                # ISO 20022 ``Ustrd`` (≤140 chars) — the operator's
                # remittance template, falling back to the internal charge
                # description only if the rendered text comes out empty.
                "description": render_remittance(
                    remittance_template,
                    creditor=creditor_name,
                    member=debtor_name,
                    charge=charge,
                )
                or (charge.description or f"Subscription {charge.subscription_id}")[
                    :140
                ],
                "endtoend_id": str(charge.end_to_end_id or charge.pk)[:35],
            }
        )

    # ``validate=True`` runs the bundled XSD against the generated
    # document and raises if anything is off — a malformed file never
    # reaches the office's download button. Translate sepaxml's opaque
    # ValidationError into our SepaExportInvalid (a clean 4xx) carrying the
    # failing element(s), so the office sees WHICH field is illegal (a
    # creditor BIC / creditor-id, an out-of-charset debtor name, a past
    # collection date, …) instead of an unhelpful 500.
    try:
        return sepa.export(validate=True)
    except SepaXmlValidationError as exc:
        raise _validation_failure(exc) from exc


def _creditor_config(tenant: Tenant) -> dict[str, object]:
    """The ``sepaxml`` config naming the farm as the creditor.

    The pain.008 export requires these fields. Fail loudly here rather than
    producing a half-built XML the bank would reject anyway.
    """
    creditor_name = tenant.sepa_creditor_name.strip()
    creditor_id = tenant.sepa_creditor_id.strip()
    creditor_iban = (tenant.iban or "").replace(" ", "")
    # ``sepaxml`` requires BIC in its config even though
    # pain.008.001.02 marks the field as optional in the actual
    # XML. The library validates the config up-front and won't
    # accept an empty BIC — so we require it here for parity.
    creditor_bic = tenant.sepa_creditor_bic.strip().upper()
    missing = [
        name
        for name, value in (
            ("Tenant.sepa_creditor_name", creditor_name),
            ("Tenant.sepa_creditor_id", creditor_id),
            ("Tenant.iban", creditor_iban),
            ("Tenant.sepa_creditor_bic", creditor_bic),
        )
        if not value
    ]
    if missing:
        raise SepaExportInvalid(
            "Cannot export SEPA XML: tenant is missing required "
            "creditor fields: " + ", ".join(missing),
            details={"missing_creditor_fields": missing},
        )
    return {
        "name": creditor_name,
        "IBAN": creditor_iban,
        "BIC": creditor_bic,
        "batch": True,
        "creditor_id": creditor_id,
        "currency": "EUR",
    }


def _validation_failure(exc: SepaXmlValidationError) -> SepaExportInvalid:
    """``sepaxml``'s failed XSD validation as the error the office sees.

    sepaxml validates via the ``xmlschema`` library; its
    XMLSchemaValidationError carries the failing element ``path`` + ``reason``
    (NOT an lxml ``error_log``). Surface the offending field (e.g. "BIC: value
    doesn't match pattern …") so the office can fix the exact tenant/debtor
    field instead of guessing.
    """
    cause = exc.__cause__ or exc.__context__
    reason = getattr(cause, "reason", None)
    path = getattr(cause, "path", None)
    field = path.rstrip("/").split("/")[-1].split("[")[0] if path else None
    if field and reason:
        detail = f"{field}: {reason}"
    elif cause is not None:
        detail = str(cause).strip().splitlines()[0]
    else:
        detail = str(exc)
    return SepaExportInvalid(
        "The generated SEPA file failed validation. Check the creditor "
        "fields (name / IBAN / BIC / creditor-id) and the debtor data. "
        f"Details: {detail}",
        details={"validation_errors": detail},
    )
