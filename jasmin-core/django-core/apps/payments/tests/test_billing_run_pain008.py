"""Pin the pain.008.001.02 SEPA XML export shape.

We rely on the ``sepaxml`` library for spec compliance + schema
validation (the library's own ``validate=True`` runs the bundled
XSD on every export, so a malformed file can never reach the
office). This suite covers what's NOT the library's job:

  * the deterministic charge ordering inside the XML (so two
    independent calls with the same input produce byte-identical
    output);
  * the creditor identity → ``InitgPty`` / ``Cdtr`` mapping
    (the dormant ``Tenant.sepa_creditor_*`` fields are now load-
    bearing);
  * sequence-type derivation: ``FRST`` on the first export of a
    mandate, ``RCUR`` thereafter;
  * the loud error paths that previously yielded silent
    half-built files (missing creditor info, missing debtor
    mandate fields).

If a future tenant wants a different pain.008 minor version (.03,
.08), keep this suite focused on .02 and add a parallel suite
under a parametrize. Mixing versions in one test would obscure
which schema is being asserted.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from xml.etree import ElementTree as ET

import pytest
import time_machine

from apps.payments.constants import ChargeStatus
from apps.payments.errors import SepaExportInvalid
from apps.payments.models import ChargeSchedule
from apps.payments.services import BillingRunService


@pytest.fixture(autouse=True)
def _frozen_today():
    """Freeze "today" to 2026-02-01 so the ``collection_date >= today`` export
    guard (RUN-2) sees the suite's fixed 2026 collection dates as still in the
    future (they pre-date the real wall clock)."""
    with time_machine.travel("2026-02-01", tick=False):
        yield


# pain.008.001.02 lives in this namespace per ISO 20022.
NS = "urn:iso:std:iso:20022:tech:xsd:pain.008.001.02"


def _make_planned_charge(
    member,
    subscription,
    *,
    due_date: datetime.date,
    amount: Decimal = Decimal("10.00"),
) -> ChargeSchedule:
    # ``ChargeSchedule`` requires ``period_start`` / ``period_end``
    # (both NOT NULL on the model). Use the calendar month containing
    # ``due_date`` — what the production charge generator would emit
    # for a monthly cycle.
    period_start = due_date.replace(day=1)
    next_month = (period_start + datetime.timedelta(days=32)).replace(day=1)
    period_end = next_month - datetime.timedelta(days=1)
    return ChargeSchedule.objects.create(
        member=member,
        subscription=subscription,
        period_start=period_start,
        period_end=period_end,
        due_date=due_date,
        expected_amount=amount,
        currency="EUR",
        status=ChargeStatus.PLANNED,
    )


def _run_with_one_charge(
    member,
    subscription,
    *,
    amount=Decimal("12.34"),
    due_date: datetime.date = datetime.date(2026, 2, 5),
):
    """Create a single PLANNED charge + a BillingRun that picks it up.

    ``due_date`` is the only parameter that influences the
    ``ChargeSchedule.period_start`` (derived as the first of that
    due_date's month). Callers that fire the helper multiple times
    against the SAME subscription must pass distinct ``due_date``
    values from different months — otherwise the second create
    collides on ``unique(subscription, period_start)``.
    """
    _make_planned_charge(member, subscription, due_date=due_date, amount=amount)
    # Build a run window broad enough to span any reasonable due_date.
    run_period_start = due_date.replace(day=1)
    next_month = (run_period_start + datetime.timedelta(days=32)).replace(day=1)
    run_period_end = next_month - datetime.timedelta(days=1)
    return BillingRunService.create_run(
        period_start=run_period_start,
        period_end=run_period_end,
        collection_date=run_period_end + datetime.timedelta(days=5),
    )


def _export_and_parse(run) -> ET.Element:
    BillingRunService.export(run)
    run.refresh_from_db()
    with run.sepa_xml_export.open("rb") as fh:
        return ET.fromstring(fh.read())


def _find(root: ET.Element, *path: str) -> ET.Element | None:
    """Find an element by sequenced child-tag path, namespace-aware."""
    cur: ET.Element | None = root
    for tag in path:
        if cur is None:
            return None
        cur = cur.find(f"{{{NS}}}{tag}")
    return cur


def _findall(root: ET.Element, *path: str) -> list[ET.Element]:
    """Like _find but returns every match for the final path segment."""
    cur: ET.Element | None = root
    for tag in path[:-1]:
        if cur is None:
            return []
        cur = cur.find(f"{{{NS}}}{tag}")
    if cur is None:
        return []
    return cur.findall(f"{{{NS}}}{path[-1]}")


@pytest.mark.django_db
class TestPain008StructureAndCreditor:
    def test_root_is_customer_direct_debit_initiation(
        self, tenant, tenant_settings, billing_profile, subscription, member
    ):
        root = _export_and_parse(_run_with_one_charge(member, subscription))
        # ``<Document><CstmrDrctDbtInitn>...`` is the pain.008 root pair.
        assert root.tag == f"{{{NS}}}Document"
        assert _find(root, "CstmrDrctDbtInitn") is not None

    def test_initiating_party_is_tenant_creditor_name(
        self, tenant, tenant_settings, billing_profile, subscription, member
    ):
        root = _export_and_parse(_run_with_one_charge(member, subscription))
        nm = _find(root, "CstmrDrctDbtInitn", "GrpHdr", "InitgPty", "Nm")
        assert nm is not None
        assert nm.text == "Test Farm e.G."  # conftest fixture

    def test_creditor_iban_is_tenant_iban(
        self, tenant, tenant_settings, billing_profile, subscription, member
    ):
        root = _export_and_parse(_run_with_one_charge(member, subscription))
        iban = _find(
            root,
            "CstmrDrctDbtInitn",
            "PmtInf",
            "CdtrAcct",
            "Id",
            "IBAN",
        )
        assert iban is not None
        assert iban.text == "DE89370400440532013000"  # conftest fixture


@pytest.mark.django_db
class TestPain008AmountAndDebtor:
    def test_amount_uses_dot_decimal_and_correct_value(
        self, tenant, tenant_settings, billing_profile, subscription, member
    ):
        """ISO 20022 uses dot as the decimal separator (NOT the German
        comma convention). 12.34 EUR must serialise as ``12.34``."""
        root = _export_and_parse(
            _run_with_one_charge(member, subscription, amount=Decimal("12.34"))
        )
        amt = _find(
            root,
            "CstmrDrctDbtInitn",
            "PmtInf",
            "DrctDbtTxInf",
            "InstdAmt",
        )
        assert amt is not None
        assert amt.text == "12.34"
        assert amt.attrib.get("Ccy") == "EUR"

    def test_debtor_name_and_iban_match_billing_profile(
        self, tenant, tenant_settings, billing_profile, subscription, member
    ):
        root = _export_and_parse(_run_with_one_charge(member, subscription))
        dbtr_nm = _find(
            root,
            "CstmrDrctDbtInitn",
            "PmtInf",
            "DrctDbtTxInf",
            "Dbtr",
            "Nm",
        )
        dbtr_iban = _find(
            root,
            "CstmrDrctDbtInitn",
            "PmtInf",
            "DrctDbtTxInf",
            "DbtrAcct",
            "Id",
            "IBAN",
        )
        assert dbtr_nm is not None and dbtr_iban is not None
        assert dbtr_nm.text == billing_profile.account_holder
        assert dbtr_iban.text == "DE89370400440532013000"

    def test_mandate_id_uses_billing_profile_reference(
        self, tenant, tenant_settings, billing_profile, subscription, member
    ):
        root = _export_and_parse(_run_with_one_charge(member, subscription))
        mandate_id = _find(
            root,
            "CstmrDrctDbtInitn",
            "PmtInf",
            "DrctDbtTxInf",
            "DrctDbtTx",
            "MndtRltdInf",
            "MndtId",
        )
        assert mandate_id is not None
        assert mandate_id.text == billing_profile.sepa_mandate_reference


@pytest.mark.django_db
class TestSequenceTypeFrstVsRcur:
    """``FRST`` (first use of a mandate) vs ``RCUR`` (subsequent
    uses). Pin the transition so a wrong stamp doesn't slip through
    silently and cause the bank to reject the file."""

    def test_first_export_is_frst(
        self, tenant, tenant_settings, billing_profile, subscription, member
    ):
        assert billing_profile.sepa_mandate_first_use_at is None
        root = _export_and_parse(_run_with_one_charge(member, subscription))
        seq = _find(
            root,
            "CstmrDrctDbtInitn",
            "PmtInf",
            "PmtTpInf",
            "SeqTp",
        )
        assert seq is not None
        assert seq.text == "FRST"
        # Side-effect: export stamped the first-use date.
        billing_profile.refresh_from_db()
        assert billing_profile.sepa_mandate_first_use_at is not None

    def test_second_export_is_rcur(
        self, tenant, tenant_settings, billing_profile, subscription, member
    ):
        # First run flips first_use_at; the second run should pick RCUR.
        _export_and_parse(_run_with_one_charge(member, subscription))
        billing_profile.refresh_from_db()
        assert billing_profile.sepa_mandate_first_use_at is not None

        # Second run uses a March due date so the new charge gets a
        # different ``period_start`` (Mar 1 vs the first charge's
        # Feb 1) and doesn't collide on
        # ``unique(subscription, period_start)``.
        root = _export_and_parse(
            _run_with_one_charge(
                member,
                subscription,
                amount=Decimal("20.00"),
                due_date=datetime.date(2026, 3, 5),
            )
        )
        seq = _find(
            root,
            "CstmrDrctDbtInitn",
            "PmtInf",
            "PmtTpInf",
            "SeqTp",
        )
        assert seq is not None
        assert seq.text == "RCUR"

    def test_multiple_new_mandate_charges_in_one_run_emit_single_frst(
        self, tenant, tenant_settings, billing_profile, subscription, member
    ):
        # Regression (CORR-2): a never-used mandate carrying several charges
        # in ONE run must produce exactly one FRST (the rest RCUR). SEPA
        # allows only one FRST per mandate; two would get the batch rejected.
        assert billing_profile.sepa_mandate_first_use_at is None
        _make_planned_charge(member, subscription, due_date=datetime.date(2026, 2, 5))
        _make_planned_charge(member, subscription, due_date=datetime.date(2026, 3, 5))
        run = BillingRunService.create_run(
            period_start=datetime.date(2026, 2, 1),
            period_end=datetime.date(2026, 3, 31),
            collection_date=datetime.date(2026, 4, 5),
        )
        root = _export_and_parse(run)
        # SeqTp lives in each PmtInf/PmtTpInf; sepaxml splits FRST and RCUR
        # into separate PmtInf blocks, so collect across all of them.
        seqs = [el.text for el in root.iter(f"{{{NS}}}SeqTp")]
        assert len(seqs) == 2, seqs
        assert seqs.count("FRST") == 1, seqs
        assert seqs.count("RCUR") == 1, seqs


@pytest.mark.django_db
class TestRequestedCollectionDate:
    """RequestedCollectionDate must be the run's operator-set
    ``collection_date`` (when the bank debits), NOT each charge's
    ``due_date`` (CORR-3)."""

    def test_uses_run_collection_date_not_charge_due_date(
        self, tenant, tenant_settings, billing_profile, subscription, member
    ):
        # ``_run_with_one_charge`` sets collection_date = period_end + 5 days,
        # which differs from the charge's Feb-5 due_date.
        run = _run_with_one_charge(
            member, subscription, due_date=datetime.date(2026, 2, 5)
        )
        root = _export_and_parse(run)
        run.refresh_from_db()
        reqd = _find(root, "CstmrDrctDbtInitn", "PmtInf", "ReqdColltnDt")
        assert reqd is not None
        assert reqd.text == run.collection_date.isoformat()
        # Explicitly NOT the per-charge due date.
        assert reqd.text != "2026-02-05"


@pytest.mark.django_db
class TestLoudFailures:
    """The dormant creditor fields are now load-bearing — missing
    values must raise BEFORE any file hits disk."""

    def test_missing_creditor_id_raises(
        self, tenant, tenant_settings, billing_profile, subscription, member
    ):
        tenant.sepa_creditor_id = ""
        tenant.save()

        run = _run_with_one_charge(member, subscription)
        with pytest.raises(SepaExportInvalid, match="sepa_creditor_id"):
            BillingRunService.export(run)

    def test_missing_creditor_name_raises(
        self, tenant, tenant_settings, billing_profile, subscription, member
    ):
        tenant.sepa_creditor_name = ""
        tenant.save()

        run = _run_with_one_charge(member, subscription)
        with pytest.raises(SepaExportInvalid, match="sepa_creditor_name"):
            BillingRunService.export(run)

    def test_missing_creditor_iban_raises(
        self, tenant, tenant_settings, billing_profile, subscription, member
    ):
        tenant.iban = ""
        tenant.save()

        run = _run_with_one_charge(member, subscription)
        with pytest.raises(SepaExportInvalid, match="iban"):
            BillingRunService.export(run)

    def test_missing_creditor_bic_raises(
        self, tenant, tenant_settings, billing_profile, subscription, member
    ):
        tenant.sepa_creditor_bic = ""
        tenant.save()

        run = _run_with_one_charge(member, subscription)
        with pytest.raises(SepaExportInvalid, match="sepa_creditor_bic"):
            BillingRunService.export(run)


@pytest.mark.django_db
class TestDeterministicOrdering:
    """Two exports of the same charge set must produce byte-identical
    XML — guards against a future ``order_by("?")`` or dict-ordered
    addition path that would silently bake nondeterminism into the
    bank artifact."""

    def test_independent_runs_with_same_inputs_match(
        self, tenant, tenant_settings, billing_profile, subscription, member
    ):
        run_a = _run_with_one_charge(member, subscription, amount=Decimal("12.34"))
        BillingRunService.export(run_a)
        run_a.refresh_from_db()
        with run_a.sepa_xml_export.open("rb") as fh:
            bytes_a = fh.read()

        # Reset and run again with the same inputs.
        ChargeSchedule.objects.all().delete()
        billing_profile.sepa_mandate_first_use_at = None
        billing_profile.save()

        run_b = _run_with_one_charge(member, subscription, amount=Decimal("12.34"))
        BillingRunService.export(run_b)
        run_b.refresh_from_db()
        with run_b.sepa_xml_export.open("rb") as fh:
            bytes_b = fh.read()

        # ``MsgId`` differs per export (timestamped UUID inside the
        # library), so strip that and the run-specific ``end_to_end_id``
        # before comparing. The remaining content — creditor identity,
        # debtor block, amounts, sequence type, ordering — must match
        # byte-for-byte.
        def _strip_volatile(blob: bytes) -> bytes:
            import re

            blob = re.sub(rb"<MsgId>[^<]+</MsgId>", b"<MsgId/>", blob)
            blob = re.sub(rb"<PmtInfId>[^<]+</PmtInfId>", b"<PmtInfId/>", blob)
            blob = re.sub(rb"<EndToEndId>[^<]+</EndToEndId>", b"<EndToEndId/>", blob)
            blob = re.sub(rb"<CreDtTm>[^<]+</CreDtTm>", b"<CreDtTm/>", blob)
            return blob

        assert _strip_volatile(bytes_a) == _strip_volatile(bytes_b)


@pytest.mark.django_db
class TestMultiChargeOrdering:
    """When multiple charges share a member they must appear in
    ``(member_id, due_date, end_to_end_id)`` order inside the XML.
    Bank reviewers scan member-by-member; scrambled rows make
    reconciliation harder. Locked here so a future ``order_by("pk")``
    elsewhere doesn't silently change the XML layout."""

    def test_charges_grouped_by_member_then_sorted_by_due_date(
        self, tenant, tenant_settings, billing_profile, subscription, member
    ):
        # Two charges in DIFFERENT months — same subscription can't
        # carry two charges with the same ``period_start``
        # (``unique(subscription, period_start)`` constraint on the
        # model). The XML order must still follow ``due_date``
        # regardless of creation order.
        _make_planned_charge(
            member,
            subscription,
            due_date=datetime.date(2026, 3, 5),  # later
            amount=Decimal("20.00"),
        )
        _make_planned_charge(
            member,
            subscription,
            due_date=datetime.date(2026, 2, 5),  # earlier
            amount=Decimal("10.00"),
        )
        run = BillingRunService.create_run(
            period_start=datetime.date(2026, 2, 1),
            period_end=datetime.date(2026, 3, 31),
            collection_date=datetime.date(2026, 4, 5),
        )
        root = _export_and_parse(run)

        # ``sepaxml`` batches by ``(sequence_type, collection_date)``,
        # so two charges with different due dates land in TWO
        # ``<PmtInf>`` blocks. Walk every transaction across all
        # PmtInfs via ``root.iter(...)`` instead of drilling into the
        # first PmtInf only.
        txs = list(root.iter(f"{{{NS}}}DrctDbtTxInf"))
        amounts = [
            tx.find(f"{{{NS}}}InstdAmt").text for tx in txs  # type: ignore[union-attr]
        ]
        # Earlier due_date first (across whichever PmtInf carries each
        # — sepaxml emits PmtInf blocks in collection-date order).
        assert amounts == ["10.00", "20.00"]


# ---------------------------------------------------------------------------
# Remittance text (the pain.008 ``Ustrd`` — what the member sees on their
# bank statement). Operator-configurable per tenant; rendered at export.
# ---------------------------------------------------------------------------
class TestRenderRemittance:
    """Unit-level coverage of the pure renderer (no sepaxml charset cleaning,
    so ``{unknown}`` tokens are visible here)."""

    def _render(self, template):
        from apps.payments.services import _render_remittance

        return _render_remittance(
            template,
            creditor="Marillenhof",
            member="Anna Huber",
            period_start=datetime.date(2026, 6, 22),
            period_end=datetime.date(2026, 6, 28),
            amount=Decimal("25.00"),
        )

    def test_all_placeholders(self):
        assert (
            self._render("{creditor} {member} {month} {period} {amount}")
            == "Marillenhof Anna Huber Juni 2026 22.06.2026–28.06.2026 25.00"
        )

    def test_unknown_token_left_intact(self):
        # A typo'd / unsupported placeholder must never raise (literal replace,
        # not str.format) — it's simply passed through.
        assert self._render("Hallo {foo} {member}") == "Hallo {foo} Anna Huber"

    def test_truncated_to_140_chars(self):
        assert len(self._render("{creditor} " * 40)) == 140


@pytest.mark.django_db
class TestRemittanceUstrd:
    """The exported ``Ustrd`` reflects the tenant template, not the internal
    ``ChargeSchedule.description``."""

    @staticmethod
    def _ustrds(root):
        return [e.text for e in root.iter(f"{{{NS}}}Ustrd")]

    def test_blank_template_uses_creditor_and_month_default(
        self, tenant, tenant_settings, billing_profile, subscription, member
    ):
        from django.db import connection

        connection.tenant.sepa_remittance_template = ""  # → default
        root = _export_and_parse(
            _run_with_one_charge(
                member, subscription, due_date=datetime.date(2026, 2, 5)
            )
        )
        # Creditor is the fixture's "Test Farm e.G."; period is February 2026.
        assert self._ustrds(root) == ["Test Farm e.G. - Februar 2026"]

    def test_custom_template_is_rendered(
        self, tenant, tenant_settings, billing_profile, subscription, member
    ):
        from django.db import connection

        connection.tenant.sepa_remittance_template = "{creditor} Beitrag {month}"
        root = _export_and_parse(
            _run_with_one_charge(
                member, subscription, due_date=datetime.date(2026, 2, 5)
            )
        )
        assert self._ustrds(root) == ["Test Farm e.G. Beitrag Februar 2026"]
