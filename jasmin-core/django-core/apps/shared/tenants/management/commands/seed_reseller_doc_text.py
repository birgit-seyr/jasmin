"""Populate the reseller-document text fields on a tenant's *current*
``TenantSettings`` overlay with realistic sample text — useful for
checking PDF layout and the configuration UI in development.

Run on the tenant subdomain (or pass ``--schema``):

    docker compose exec backend python manage.py \\
        seed_reseller_doc_text --schema test_tenant

Idempotent: re-running overwrites the same fields on the current
TenantSettings row without creating a new version. Pass ``--reset``
to blank them all out instead.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django_tenants.utils import schema_context

from apps.shared.tenants.models import Tenant, TenantSettings

# Sample text per field. Single-line ``entry_line_2/3`` and
# ``greeting_line_2/3`` are capped to 100 chars in the UI; the strings
# below stay well under that. Multi-line fields (footers, offer
# instructions) get richer paragraph content so PDF wrapping can be
# eyeballed.
SAMPLE_TEXT: dict[str, str] = {
    # ----- Invoice -----
    "entry_line_1_invoice_reseller": (
        "Vielen Dank für Ihre Bestellung. " "Anbei erhalten Sie unsere Rechnung."
    ),
    "entry_line_2_invoice_reseller": (
        "Bitte überweisen Sie den Rechnungsbetrag unter Angabe der " "Rechnungsnummer."
    ),
    "entry_line_3_invoice_reseller": (
        "Bei Rückfragen zur Rechnung wenden Sie sich gerne an unsere " "Buchhaltung."
    ),
    "greeting_line_1_invoice_reseller": ("Mit freundlichen Grüßen aus dem Marillenhof"),
    "greeting_line_2_invoice_reseller": "Ihr Marillenhof-Team",
    "greeting_line_3_invoice_reseller": "buchhaltung@marillenhof.example",
    # ----- Delivery note -----
    "entry_line_1_delivery_note_reseller": ("Sehr geehrte Damen und Herren,"),
    "entry_line_2_delivery_note_reseller": (
        "anbei der Lieferschein für die heutige Lieferung."
    ),
    "entry_line_3_delivery_note_reseller": (
        "Bitte prüfen Sie die Ware bei Annahme auf Vollständigkeit."
    ),
    "greeting_line_1_delivery_note_reseller": ("Mit freundlichen Grüßen"),
    "greeting_line_2_delivery_note_reseller": "Ihr Marillenhof-Team",
    "greeting_line_3_delivery_note_reseller": "lieferung@marillenhof.example",
    # ----- Offer -----
    "entry_line_1_offer_reseller": ("Sehr geehrte Damen und Herren,"),
    "entry_line_2_offer_reseller": (
        "anbei unser aktuelles Angebot für die kommende Lieferwoche."
    ),
    "entry_line_3_offer_reseller": (
        "Alle Preise verstehen sich netto, zzgl. der gesetzlichen Steuer."
    ),
    "order_instructions_offer_reseller": (
        "<p><strong>Bestellannahme:</strong> Bitte tragen Sie die "
        "gewünschte Menge in der letzten Spalte ein und senden Sie das "
        "Angebot ausgefüllt zurück an "
        '<a href="mailto:bestellungen@marillenhof.example">'
        "bestellungen@marillenhof.example</a>.</p>"
        "<p>Bestellschluss ist jeden Donnerstag, 12:00 Uhr. Spätere "
        "Bestellungen können nicht garantiert berücksichtigt werden.</p>"
    ),
    "greeting_line_1_offer_reseller": ("Wir freuen uns auf Ihre Bestellung"),
    "greeting_line_2_offer_reseller": "Ihr Marillenhof-Team",
    "greeting_line_3_offer_reseller": "bestellungen@marillenhof.example",
    # ----- Footer (shared across all three doc types) -----
    "left_column_footer_documents_reseller": (
        "<p><strong>Marillenhof CSA</strong><br/>"
        "Hauptstraße 42<br/>"
        "3500 Krems an der Donau<br/>"
        "Österreich</p>"
        "<p>+43 1 234 5678<br/>"
        "office@marillenhof.example</p>"
    ),
    "middle_column_footer_documents_reseller": (
        "<p><strong>Bankverbindung</strong><br/>"
        "Raiffeisen Krems<br/>"
        "IBAN: AT12 3456 7890 1234 5678<br/>"
        "BIC: RZOOAT2L</p>"
        "<p>UID: ATU12345678</p>"
    ),
    "right_column_footer_documents_reseller": (
        "<p><strong>Geschäftsführung</strong><br/>"
        "Maria Marillenbauer<br/>"
        "Firmenbuchnummer: FN 123456 a<br/>"
        "Firmenbuchgericht: LG Krems</p>"
        "<p>Bio-Kontrollnummer: AT-BIO-301</p>"
    ),
}


class Command(BaseCommand):
    help = (
        "Seed reseller-document text fields (entry / greeting / footer / "
        "order instructions) on a tenant's current TenantSettings overlay."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--schema",
            help=(
                "Tenant schema name to seed. If omitted, uses the active "
                "tenant from the request context (i.e. set --schema when "
                "running outside a request, like ``manage.py`` shell)."
            ),
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Blank out all the seeded fields instead of writing samples.",
        )

    def handle(self, *args: Any, **opts: Any) -> None:
        schema_name = opts.get("schema")
        reset = opts.get("reset", False)

        if not schema_name:
            raise CommandError(
                "Pass --schema <schema_name>. The command runs against a "
                "specific tenant's TenantSettings overlay; we don't infer "
                "the tenant in a one-off CLI invocation."
            )

        # ``Tenant`` and ``TenantSettings`` are SHARED_APPS models so they
        # live in the public schema. Wrap the full lookup + write so the
        # connection's schema is unambiguous regardless of how
        # ``manage.py`` is invoked.
        with schema_context("public"):
            try:
                tenant = Tenant.objects.get(schema_name=schema_name)
            except Tenant.DoesNotExist as exc:
                raise CommandError(
                    f"No tenant with schema_name={schema_name!r}."
                ) from exc

            current_settings = TenantSettings.get_current_settings(tenant)
            if current_settings is None:
                raise CommandError(
                    f"Tenant {schema_name!r} has no current TenantSettings "
                    "row. Create one first (provisioning normally seeds "
                    "this automatically)."
                )

            payload = {key: "" for key in SAMPLE_TEXT} if reset else SAMPLE_TEXT

            updated = []
            for field, text in payload.items():
                setattr(current_settings, field, text)
                updated.append(field)

            current_settings.save(update_fields=updated)

        action = "Cleared" if reset else "Seeded"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} {len(updated)} reseller-document text fields on "
                f"tenant '{schema_name}' (TenantSettings id={current_settings.id})."
            )
        )
