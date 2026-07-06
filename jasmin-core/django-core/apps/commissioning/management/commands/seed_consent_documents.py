"""Seed one active ``ConsentDocument`` per ``ConsentKind`` for a tenant —
handy for exercising the registration consents, the NewSubscriptionModal
subscription-contract gate, and the consent-download PDFs in development.

Run on a tenant schema (ConsentDocument is a per-tenant model):

    docker compose exec backend python manage.py \\
        seed_consent_documents --schema test_tenant

Idempotent: only kinds that have NO document yet (for the given locale) are
created; existing ones are left untouched (so member consent records keep
pointing at the same row). The sample bodies are obvious placeholders — swap
in the real legal text via Configuration → Consents before going live.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django_tenants.utils import schema_context

from apps.commissioning.models.choices_text import ConsentKind
from apps.commissioning.models.consents import ConsentDocument
from apps.shared.tenants.models import Tenant

# Placeholder title + HTML body per kind. German (the primary locale); clearly
# marked as sample text so nobody mistakes it for the real legal document.
_SAMPLE = "<p><em>Beispieltext zum Testen — bitte vor dem Live-Gang durch den "
_SAMPLE += "echten Rechtstext ersetzen.</em></p>"

BODIES: dict[str, tuple[str, str]] = {
    ConsentKind.PRIVACY: (
        "Datenschutzerklärung",
        _SAMPLE + "<p>Wir verarbeiten deine personenbezogenen Daten ausschließlich zur "
        "Abwicklung deiner Mitgliedschaft und deiner Ernte-Anteile gemäß "
        "DSGVO. Deine Daten werden nicht an Dritte weitergegeben.</p>",
    ),
    ConsentKind.SEPA: (
        "SEPA-Lastschriftmandat",
        _SAMPLE + "<p>Ich ermächtige den Betrieb, Zahlungen von meinem Konto mittels "
        "SEPA-Lastschrift einzuziehen, und weise mein Kreditinstitut an, die "
        "Lastschriften einzulösen.</p>",
    ),
    ConsentKind.WITHDRAWAL: (
        "Widerrufsbelehrung",
        _SAMPLE + "<p>Du hast das Recht, binnen vierzehn Tagen ohne Angabe von Gründen "
        "diesen Vertrag zu widerrufen. Die Widerrufsfrist beträgt vierzehn "
        "Tage ab Vertragsschluss.</p>",
    ),
    ConsentKind.TERMS: (
        "Allgemeine Geschäftsbedingungen",
        _SAMPLE + "<p>Diese Bedingungen regeln das Verhältnis zwischen dir und dem "
        "Betrieb rund um Mitgliedschaft, Ernte-Anteile und Lieferung.</p>",
    ),
    ConsentKind.COOP_CONTRACT: (
        "Zeichnungsvertrag Genossenschaftsanteile",
        _SAMPLE + "<p>Mit der Zeichnung von Genossenschaftsanteilen wirst du Mitglied "
        "der Genossenschaft. Jeder Anteil begründet Rechte und Pflichten "
        "gemäß Satzung.</p>",
    ),
    ConsentKind.SUBSCRIPTION_CONTRACT: (
        "Abo-Vertrag",
        _SAMPLE + "<p>Mit diesem Vertrag bestellst du einen Ernte-Anteil für die "
        "vereinbarte Laufzeit. Die Ernte wird solidarisch getragen; der "
        "Beitrag wird gemäß dem gewählten Zahlungsrhythmus eingezogen.</p>",
    ),
}


class Command(BaseCommand):
    help = (
        "Seed one active ConsentDocument per ConsentKind (privacy, sepa, "
        "withdrawal, terms, coop_contract, subscription_contract) for a tenant."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--schema",
            required=True,
            help="Tenant schema name to seed the consent documents into.",
        )
        parser.add_argument(
            "--locale",
            default="de",
            help="Locale code for the seeded documents (default: de).",
        )
        parser.add_argument(
            "--no-pdf",
            action="store_true",
            help=(
                "Skip eager PDF rendering (WeasyPrint). The PDF renders lazily "
                "on first download anyway."
            ),
        )

    def handle(self, *args: Any, **opts: Any) -> None:
        schema_name: str = opts["schema"]
        locale: str = opts["locale"]
        render_pdf: bool = not opts["no_pdf"]

        # ``Tenant`` is a SHARED model (public schema); validate it exists there
        # before switching into the tenant schema to write the documents.
        with schema_context("public"):
            if not Tenant.objects.filter(schema_name=schema_name).exists():
                raise CommandError(f"No tenant with schema_name={schema_name!r}.")

        today = timezone.now().date()
        created: list[str] = []
        skipped: list[str] = []

        with schema_context(schema_name):
            for kind, (title, body) in BODIES.items():
                # Idempotent: only seed a kind that has NO document yet for this
                # locale, so we never orphan a version members already consented
                # to (deleting/replacing those is intentionally protected).
                if ConsentDocument.objects.filter(kind=kind, locale=locale).exists():
                    skipped.append(kind)
                    continue

                document = ConsentDocument.objects.create(
                    kind=kind,
                    version="1.0",
                    locale=locale,
                    title=title,
                    body=body,
                    valid_from=today,
                    valid_until=None,  # open-ended → the current version
                )
                if render_pdf:
                    # Best-effort, mirroring the viewset's perform_create: a
                    # render hiccup must not fail seeding (download regenerates).
                    try:
                        document.ensure_pdf()
                    except Exception as exc:  # noqa: BLE001
                        self.stderr.write(
                            self.style.WARNING(
                                f"PDF render failed for {kind} "
                                f"(id={document.id}): {exc}"
                            )
                        )
                created.append(kind)

        self.stdout.write(
            self.style.SUCCESS(
                f"Consent documents on tenant '{schema_name}' (locale={locale}): "
                f"{len(created)} created"
                + (f" [{', '.join(created)}]" if created else "")
                + f", {len(skipped)} already present"
                + (f" [{', '.join(skipped)}]" if skipped else "")
                + "."
            )
        )
