"""Email template registry — single source of truth for tenant-editable
email templates.

Each entry maps a stable ``slug`` (used by code, by the API, and by the
React editor) to:

    label             Human-readable name shown in the admin UI.
    description       One-line explanation of when this email is sent.
    default_template  Path of the on-disk Django template used as the
                      shipped default. Rendered with the full Django
                      template engine.
    default_subject   Default subject line; tenants may override.
    variables         List of EmailVariable entries describing each
                      placeholder available to this template.
    sample            Sample context used to render a realistic test-send /
                      i18n snapshot (every {{var}} placeholder populated).

Slugs are namespaced by app: ``accounts.invitation``, ``commissioning.offer``.

NOTE: defaults are rendered via Django's template engine (full power, since
they are authored by us). Tenant overrides are rendered via the safe
Mustache-style renderer in ``apps.notifications.template_renderer`` —
``{{var.path}}`` substitutions only, no logic, no filters.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from apps.shared.languages import DEFAULT_LANGUAGE_CODE, SUPPORTED_LANGUAGE_CODES

# Languages we ship templates for. The first one is the fallback when a
# requested language has no on-disk file or DB override. Derived from the
# single source in apps/shared/languages.py so this and the accounts
# user_language choices can't drift.
SUPPORTED_LANGUAGES: tuple[str, ...] = SUPPORTED_LANGUAGE_CODES
DEFAULT_LANGUAGE: str = DEFAULT_LANGUAGE_CODE


def normalize_language(raw: str | None) -> str | None:
    """Map a free-form language value to one of SUPPORTED_LANGUAGES.

    Accepts ``de``, ``de-DE``, ``de_DE``, ``deutsch``, ``german``, ``en``,
    ``en-US``, ``english``, etc. Returns ``None`` if no supported match — so
    callers can fall through to a tenant/default language rather than silently
    mis-resolving a template against an unsupported code.

    Lives here (beside SUPPORTED_LANGUAGES) so the shared EmailService and the
    notifications viewsets share ONE normalizer instead of two parallel ones.
    """
    if not raw:
        return None
    val = str(raw).strip().lower().replace("_", "-")
    if not val:
        return None
    aliases = {
        "de": "de",
        "deu": "de",
        "ger": "de",
        "deutsch": "de",
        "german": "de",
        "en": "en",
        "eng": "en",
        "english": "en",
        "englisch": "en",
    }
    if val in aliases and aliases[val] in SUPPORTED_LANGUAGES:
        return aliases[val]
    head = val.split("-", 1)[0]
    if head in aliases and aliases[head] in SUPPORTED_LANGUAGES:
        return aliases[head]
    if head in SUPPORTED_LANGUAGES:
        return head
    return None


def template_path(stem: str, language: str, ext: str) -> str:
    """Build a per-language template path: ``<stem>.<lang>.<ext>``."""
    return f"{stem}.{language}.{ext}"


@dataclass(frozen=True)
class EmailVariable:
    """A placeholder available inside an email template.

    name        Dotted path used in the template, e.g. ``user.first_name``.
                Inserted into the body as ``{{ user.first_name }}``.
    label       Short, human-friendly name shown as a chip in the editor.
                Speaks the user's language ("Vorname Mitglied" not
                "user.first_name").
    description Longer explanation shown in the chip's tooltip.
    """

    name: str
    label: str
    description: str = ""


@dataclass(frozen=True)
class EmailTemplateSpec:
    slug: str
    label: str
    description: str
    # Stem of the on-disk default template (NO extension, NO language
    # suffix). The renderer appends ``.<lang>.html`` / ``.<lang>.txt``.
    # Example: ``accounts/emails/invitation``.
    default_template: str
    # ``default_subject`` is the German (source-of-truth) subject; the bodies are
    # per-language files but the subject was single-valued, so an English send
    # shipped an English body under a German subject (EML-5). ``default_subject_en``
    # supplies the English subject; _resolve_template picks by send language.
    default_subject: str
    default_subject_en: str | None = None
    default_subject_fr: str | None = None
    default_subject_it: str | None = None
    # Grouping shown in the admin UI. One of CATEGORY_ORDER below.
    category: str = "users"
    variables: list[EmailVariable] = field(default_factory=list)
    sample: dict[str, object] = field(default_factory=dict)

    def subject_for(self, language: str) -> str:
        """The default subject in ``language``, falling back to the German
        ``default_subject`` when no language-specific subject is defined —
        mirrors the per-language body fallback in ``EmailService``."""
        return {
            "en": self.default_subject_en,
            "fr": self.default_subject_fr,
            "it": self.default_subject_it,
        }.get(language) or self.default_subject


# Display order for the admin UI. Templates are grouped and sorted by
# this order; within a group they are ordered by slug.
CATEGORY_ORDER: tuple[str, ...] = ("members", "resellers", "users", "office")
CATEGORY_LABELS: dict[str, str] = {
    "members": "Mitglieder",
    "resellers": "Wiederverkäufer",
    "users": "Konten",
    # EML-11: the gdpr.deletion_pending_admin_office spec uses category="office";
    # without this it sorted to the bottom with a raw, untranslated "office" label.
    "office": "Büro",
}


# Reusable variable definitions
_TENANT_NAME = EmailVariable(
    name="tenant_name",
    label="Name der Genossenschaft",
    description="Der angezeigte Name eurer Solawi.",
)
_USER_FIRST = EmailVariable(
    name="user.first_name",
    label="Vorname Empfänger:in",
    description="Vorname der Person, die die E-Mail erhält.",
)
_USER_EMAIL = EmailVariable(
    name="user.email",
    label="E-Mail Empfänger:in",
    description="E-Mail-Adresse der Person, die die E-Mail erhält.",
)
_APPLICANT_FIRST = EmailVariable(
    name="applicant.first_name",
    label="Vorname Antragsteller:in",
    description="Vorname der Person, die den Antrag gestellt hat.",
)
# The member-application lifecycle templates (received / approved / rejected)
# are rendered with a ``member.*`` context built by the registration and
# member services — the shipped default templates reference these directly.
# They must be declared so a tenant override that copies the default isn't
# rejected as referencing an undeclared placeholder.
_MEMBER_FIRST = EmailVariable(
    name="member.first_name",
    label="Vorname Mitglied",
    description="Vorname der antragstellenden Person.",
)
_MEMBER_EMAIL = EmailVariable(
    name="member.email",
    label="E-Mail Mitglied",
    description="E-Mail-Adresse der antragstellenden Person.",
)
_MEMBER_NUMBER = EmailVariable(
    name="member.member_number",
    label="Mitgliedsnummer",
    description="Mitgliedsnummer der antragstellenden Person (falls vergeben).",
)
_MEMBER_REJECTION_REASON = EmailVariable(
    name="member.admin_rejection_reason",
    label="Ablehnungsgrund",
    description="Vom Büro hinterlegte Begründung einer Ablehnung (falls vorhanden).",
)
_RESELLER_NAME = EmailVariable(
    name="reseller.name",
    label="Name Wiederverkäufer",
    description="Geschäftsname des Wiederverkäufers.",
)
_INVOICE_NUMBER = EmailVariable(
    name="invoice.number",
    label="Rechnungsnummer",
    description="Eindeutige Rechnungsnummer.",
)
_INVOICE_TOTAL = EmailVariable(
    name="invoice.total",
    label="Rechnungsbetrag",
    description="Gesamtbetrag inklusive Währung.",
)
_TENANT_BANK = EmailVariable(
    name="tenant.bank_details",
    label="Bankverbindung",
    description="Bankverbindung der Solawi für die Überweisung.",
)


REGISTRY: dict[str, EmailTemplateSpec] = {
    "accounts.invitation": EmailTemplateSpec(
        slug="accounts.invitation",
        label="Einladung",
        description="Wird gesendet, wenn ein Admin eine neue Person einlädt, ein Passwort zu setzen.",
        default_template="accounts/emails/invitation",
        default_subject="Du wurdest zu {{ tenant_name }} eingeladen",
        default_subject_en="You've been invited to {{ tenant_name }}",
        default_subject_fr="Vous avez été invité·e à rejoindre {{ tenant_name }}",
        default_subject_it="Hai ricevuto un invito da {{ tenant_name }}",
        category="users",
        variables=[
            _TENANT_NAME,
            _USER_FIRST,
            _USER_EMAIL,
            EmailVariable(
                name="accept_url",
                label="Einladungslink",
                description="Einmaliger Link, um das Passwort zu setzen.",
            ),
            EmailVariable(
                name="expires_at",
                label="Gültig bis",
                description="Zeitpunkt, zu dem der Einladungslink abläuft.",
            ),
        ],
        sample={
            "tenant_name": "Beispiel-Solawi",
            "user": {"first_name": "Maria", "email": "maria@example.org"},
            "accept_url": "https://app.example.org/invite/abc123",
            "expires_at": "31.12.2026, 23:59",
        },
    ),
    "accounts.email_verification_code": EmailTemplateSpec(
        slug="accounts.email_verification_code",
        label="Registrierung: E-Mail-Code",
        description=(
            "Wird während der öffentlichen Registrierung gesendet, um die "
            "E-Mail-Adresse der antragstellenden Person zu bestätigen."
        ),
        default_template="accounts/emails/email_verification_code",
        default_subject="Dein Bestätigungscode — {{ tenant_name }}",
        default_subject_en="Your verification code — {{ tenant_name }}",
        default_subject_fr="Votre code de vérification — {{ tenant_name }}",
        default_subject_it="Il tuo codice di verifica — {{ tenant_name }}",
        category="members",
        variables=[
            _TENANT_NAME,
            EmailVariable(
                name="first_name",
                label="Vorname",
                description="Vorname aus dem Registrierungsformular (kann leer sein).",
            ),
            EmailVariable(
                name="code",
                label="Bestätigungscode",
                description="Der sechsstellige Code, den die Person eingeben muss.",
            ),
        ],
        sample={
            "tenant_name": "Beispiel-Solawi",
            "first_name": "Lukas",
            "code": "428913",
        },
    ),
    "accounts.password_reset": EmailTemplateSpec(
        slug="accounts.password_reset",
        label="Passwort zurücksetzen",
        description="Wird gesendet, wenn jemand auf 'Passwort vergessen?' klickt.",
        default_template="accounts/emails/password_reset",
        default_subject="Setze dein Passwort für {{ tenant_name }} zurück",
        default_subject_en="Reset your password for {{ tenant_name }}",
        default_subject_fr="Réinitialisez votre mot de passe pour {{ tenant_name }}",
        default_subject_it="Reimposta la tua password per {{ tenant_name }}",
        category="users",
        variables=[
            _TENANT_NAME,
            _USER_FIRST,
            EmailVariable(
                name="reset_url",
                label="Reset-Link",
                description="Einmaliger Link zum Setzen eines neuen Passworts.",
            ),
            EmailVariable(
                name="expires_minutes",
                label="Gültigkeit (Minuten)",
                description="Wie lange der Link gültig ist (in Minuten).",
            ),
        ],
        sample={
            "tenant_name": "Beispiel-Solawi",
            "user": {"first_name": "Maria"},
            "reset_url": "https://app.example.org/reset/xyz789",
            "expires_minutes": "60",
        },
    ),
    "accounts.application_received": EmailTemplateSpec(
        slug="accounts.application_received",
        label="Mitgliedsantrag eingegangen",
        description="Automatische Bestätigung nach Absenden des öffentlichen Beitrittsformulars.",
        default_template="accounts/emails/application_received",
        default_subject="Wir haben deinen Antrag erhalten — {{ tenant_name }}",
        default_subject_en="We've received your application — {{ tenant_name }}",
        default_subject_fr="Nous avons bien reçu votre demande — {{ tenant_name }}",
        default_subject_it="Abbiamo ricevuto la tua richiesta — {{ tenant_name }}",
        category="members",
        variables=[
            _TENANT_NAME,
            _MEMBER_FIRST,
            _MEMBER_EMAIL,
            _APPLICANT_FIRST,
            EmailVariable(
                name="applicant.email",
                label="E-Mail Antragsteller:in",
                description="E-Mail-Adresse aus dem Antragsformular.",
            ),
        ],
        sample={
            "tenant_name": "Beispiel-Solawi",
            "member": {"first_name": "Lukas", "email": "lukas@example.org"},
            "applicant": {"first_name": "Lukas", "email": "lukas@example.org"},
        },
    ),
    "accounts.application_approved": EmailTemplateSpec(
        slug="accounts.application_approved",
        label="Mitgliedsantrag angenommen",
        description="Wird versendet, nachdem das Büro einen offenen Antrag bestätigt.",
        default_template="accounts/emails/application_approved",
        default_subject="Willkommen als Mitglied bei {{ tenant_name }}!",
        default_subject_en="Welcome as a member of {{ tenant_name }}!",
        default_subject_fr="Bienvenue en tant que membre de {{ tenant_name }} !",
        default_subject_it="Benvenuto·a come membro di {{ tenant_name }}!",
        category="members",
        variables=[
            _TENANT_NAME,
            _MEMBER_FIRST,
            _MEMBER_NUMBER,
            _APPLICANT_FIRST,
            EmailVariable(
                name="next_steps_url",
                label="Onboarding-Link",
                description="Link zur Onboarding-Seite mit nächsten Schritten.",
            ),
        ],
        sample={
            "tenant_name": "Beispiel-Solawi",
            "member": {"first_name": "Lukas", "member_number": "204"},
            "applicant": {"first_name": "Lukas"},
            "next_steps_url": "https://app.example.org/onboarding",
        },
    ),
    "accounts.application_rejected": EmailTemplateSpec(
        slug="accounts.application_rejected",
        label="Mitgliedsantrag abgelehnt",
        description="Wird versendet, wenn das Büro einen Antrag nicht annehmen kann.",
        default_template="accounts/emails/application_rejected",
        default_subject="Zu deinem Antrag bei {{ tenant_name }}",
        default_subject_en="About your application at {{ tenant_name }}",
        default_subject_fr="Au sujet de votre demande auprès de {{ tenant_name }}",
        default_subject_it="In merito alla tua richiesta presso {{ tenant_name }}",
        category="members",
        variables=[
            _TENANT_NAME,
            _MEMBER_FIRST,
            _MEMBER_NUMBER,
            _MEMBER_REJECTION_REASON,
            _APPLICANT_FIRST,
            EmailVariable(
                name="reason",
                label="Begründung",
                description="Optionaler Freitext mit der Begründung der Ablehnung.",
            ),
        ],
        sample={
            "tenant_name": "Beispiel-Solawi",
            "member": {
                "first_name": "Lukas",
                "member_number": "204",
                "admin_rejection_reason": "Für diese Saison sind alle Anteile vergeben.",
            },
            "applicant": {"first_name": "Lukas"},
            "reason": "Für diese Saison sind alle Anteile vergeben.",
        },
    ),
    "accounts.welcome_user": EmailTemplateSpec(
        slug="accounts.welcome_user",
        label="Konto aktiviert",
        description=(
            "Wird gesendet, sobald ein Benutzerkonto aktiv geschaltet "
            "wurde (z. B. nach Annahme einer Einladung). Trifft jedes "
            "neue Konto — Mitglied, Büro, Admin — nicht nur Mitglieder."
        ),
        default_template="accounts/emails/welcome_user",
        default_subject="Dein Konto bei {{ tenant_name }} ist aktiv",
        default_subject_en="Your account at {{ tenant_name }} is active",
        default_subject_fr="Votre compte chez {{ tenant_name }} est activé",
        default_subject_it="Il tuo account presso {{ tenant_name }} è attivo",
        category="users",
        variables=[
            _TENANT_NAME,
            _USER_FIRST,
            EmailVariable(
                name="portal_url",
                label="Portal-Link",
                description="Login-Adresse des Mitgliederportals.",
            ),
        ],
        sample={
            "tenant_name": "Beispiel-Solawi",
            "user": {"first_name": "Maria"},
            "portal_url": "https://app.example.org",
        },
    ),
    "commissioning.trial_converted": EmailTemplateSpec(
        slug="commissioning.trial_converted",
        label="Vollmitgliedschaft erreicht",
        description=(
            "Wird gesendet, sobald ein Probemitglied seinen ersten "
            "Geschaeftsanteil erworben hat und damit GenG-Mitglied wird."
        ),
        default_template="commissioning/emails/trial_converted",
        default_subject="Du bist jetzt Mitglied bei {{ tenant_name }}",
        default_subject_en="You're now a member of {{ tenant_name }}",
        default_subject_fr="Vous êtes désormais membre de {{ tenant_name }}",
        default_subject_it="Ora sei membro di {{ tenant_name }}",
        category="members",
        variables=[
            _TENANT_NAME,
            EmailVariable(
                name="member.first_name",
                label="Vorname Mitglied",
                description="Vorname des neuen Vollmitglieds.",
            ),
            EmailVariable(
                name="member.member_number",
                label="Mitgliedsnummer",
                description=(
                    "Mit der Umwandlung vergebene laufende "
                    "Mitgliedsnummer (GenG §30)."
                ),
            ),
            EmailVariable(
                name="entry_date",
                label="Eintrittsdatum",
                description=(
                    "Lokales Kalenderdatum des Eintritts in die "
                    "Genossenschaft (GenG §30 Eintrittsdatum)."
                ),
            ),
            EmailVariable(
                name="portal_url",
                label="Portal-Link",
                description="Login-Adresse des Mitgliederportals.",
            ),
        ],
        sample={
            "tenant_name": "Beispiel-Solawi",
            "member": {
                "first_name": "Lukas",
                "member_number": "204",
            },
            "entry_date": "01.06.2026",
            "portal_url": "https://app.example.org",
        },
    ),
    "commissioning.waiting_list_offer": EmailTemplateSpec(
        slug="commissioning.waiting_list_offer",
        label="Warteliste: Platz frei",
        description=(
            "Wird an ein Wartelisten-Mitglied gesendet, wenn das Büro einen "
            "frei gewordenen Platz anbietet. Enthält einen Einmal-Link zum "
            "Annehmen oder Ablehnen — ohne Login."
        ),
        default_template="commissioning/emails/waiting_list_offer",
        default_subject="Ein Platz ist frei geworden bei {{ tenant_name }}",
        default_subject_en="A spot has opened up at {{ tenant_name }}",
        default_subject_fr="Une place s'est libérée chez {{ tenant_name }}",
        default_subject_it="Si è liberato un posto presso {{ tenant_name }}",
        category="members",
        variables=[
            _TENANT_NAME,
            _MEMBER_FIRST,
            EmailVariable(
                name="variation_name",
                label="Anteilsart",
                description="Name der angebotenen Anteilsart.",
            ),
            EmailVariable(
                name="delivery_station_name",
                label="Verteilstation",
                description="Verteilstation/Liefertag des Abos.",
            ),
            EmailVariable(
                name="valid_from",
                label="Startdatum",
                description="Startdatum des Abos.",
            ),
            EmailVariable(
                name="accept_url",
                label="Annehmen-Link",
                description="Einmaliger Link zum Annehmen oder Ablehnen des Platzes.",
            ),
            EmailVariable(
                name="expires_at",
                label="Frist",
                description="Bis wann das Angebot gültig ist.",
            ),
        ],
        sample={
            "tenant_name": "Beispiel-Solawi",
            "member": {"first_name": "Maria"},
            "variation_name": "Ernteanteil M",
            "delivery_station_name": "Mo - Markthalle",
            "valid_from": "06.07.2026",
            "accept_url": "https://app.example.org/waiting_list-offer/abc123",
            "expires_at": "13.07.2026, 23:59",
        },
    ),
    "commissioning.member_cancelled": EmailTemplateSpec(
        slug="commissioning.member_cancelled",
        label="Austritt bestätigt",
        description=(
            "Wird gesendet, nachdem das Büro einen Austritt aus der "
            "Genossenschaft eingetragen hat (GenG §65 Kündigung). "
            "Bestätigt das Austrittsdatum und nennt die Mitglieds"
            "nummer für die Akte."
        ),
        default_template="commissioning/emails/member_cancelled",
        default_subject="Bestätigung deines Austritts bei {{ tenant_name }}",
        default_subject_en="Confirmation of your cancellation at {{ tenant_name }}",
        default_subject_fr="Confirmation de votre départ de {{ tenant_name }}",
        default_subject_it="Conferma del tuo recesso da {{ tenant_name }}",
        category="members",
        variables=[
            _TENANT_NAME,
            EmailVariable(
                name="member.first_name",
                label="Vorname Mitglied",
                description="Vorname der austretenden Person.",
            ),
            EmailVariable(
                name="member.member_number",
                label="Mitgliedsnummer",
                description=(
                    "Bestehende Mitgliedsnummer der austretenden "
                    "Person (für Akte und Auseinandersetzungs"
                    "guthaben relevant)."
                ),
            ),
            EmailVariable(
                name="cancelled_effective_at",
                label="Austrittsdatum",
                description=(
                    "Lokales Kalenderdatum, zu dem die Mitgliedschaft "
                    "endet (GenG §30 Austrittsdatum, typischerweise "
                    "ein Jahresende nach Kündigungsfrist)."
                ),
            ),
        ],
        sample={
            "tenant_name": "Beispiel-Solawi",
            "member": {
                "first_name": "Lukas",
                "member_number": "204",
            },
            "cancelled_effective_at": "31.12.2026",
        },
    ),
    "commissioning.member_self_cancelled_office": EmailTemplateSpec(
        slug="commissioning.member_self_cancelled_office",
        label="Selbstkündigung eines Mitglieds (Büro)",
        description=(
            "Wird an das Büro gesendet, wenn ein Mitglied seine "
            "Mitgliedschaft selbst über das Portal kündigt — damit das "
            "Büro den Austritt prüfen kann."
        ),
        default_template="commissioning/emails/member_self_cancelled_office",
        default_subject=(
            "Selbstkündigung: {{ member.first_name }} {{ member.last_name }}"
        ),
        default_subject_en=(
            "Self-cancellation: {{ member.first_name }} {{ member.last_name }}"
        ),
        default_subject_fr=(
            "Résiliation volontaire : {{ member.first_name }} {{ member.last_name }}"
        ),
        default_subject_it=(
            "Recesso volontario: {{ member.first_name }} {{ member.last_name }}"
        ),
        category="office",
        variables=[
            _TENANT_NAME,
            EmailVariable(
                name="member.first_name",
                label="Vorname Mitglied",
                description="Vorname der austretenden Person.",
            ),
            EmailVariable(
                name="member.last_name",
                label="Nachname Mitglied",
                description="Nachname der austretenden Person.",
            ),
            EmailVariable(
                name="member.member_number",
                label="Mitgliedsnummer",
                description="Mitgliedsnummer der austretenden Person.",
            ),
            EmailVariable(
                name="cancelled_effective_at",
                label="Austrittsdatum",
                description=(
                    "Lokales Kalenderdatum, zu dem die Mitgliedschaft endet "
                    "(GenG §30 Austrittsdatum)."
                ),
            ),
            EmailVariable(
                name="review_url",
                label="Link zur Mitgliederverwaltung",
                description="Link zum Mitglied für die Prüfung des Austritts.",
            ),
        ],
        sample={
            "tenant_name": "Beispiel-Solawi",
            "member": {
                "first_name": "Lukas",
                "last_name": "Meyer",
                "member_number": "204",
            },
            "cancelled_effective_at": "31.12.2026",
            "review_url": "https://beispiel.example/members/members/204",
        },
    ),
    "commissioning.subscription_renewal_failures_office": EmailTemplateSpec(
        slug="commissioning.subscription_renewal_failures_office",
        label="Automatische Verlängerung: fehlgeschlagene Abos (Büro)",
        description=(
            "Wird an das Büro gesendet, wenn beim nächtlichen automatischen "
            "Verlängerungslauf ein oder mehrere Abos NICHT verlängert werden "
            "konnten (z. B. keine passende Anteils-Variante deckt die neue "
            "Laufzeit ab, oder der Verteilstationstag reicht nicht hinein) — "
            "damit das Büro die betroffenen Mitglieder prüfen und ggf. manuell "
            "verlängern kann."
        ),
        default_template="commissioning/emails/subscription_renewal_failures_office",
        default_subject=(
            "Automatische Verlängerung: {{ failure_count }} Abo(s) nicht verlängert"
        ),
        default_subject_en=(
            "Auto-renewal: {{ failure_count }} subscription(s) could not be renewed"
        ),
        default_subject_fr=(
            "Renouvellement automatique : {{ failure_count }} abonnement(s) non renouvelé(s)"
        ),
        default_subject_it=(
            "Rinnovo automatico: {{ failure_count }} abbonamento/i non rinnovato/i"
        ),
        category="office",
        variables=[
            _TENANT_NAME,
            EmailVariable(
                name="failure_count",
                label="Anzahl fehlgeschlagener Abos",
                description="Anzahl der Abos, die in diesem Lauf nicht verlängert werden konnten.",
            ),
            EmailVariable(
                name="run_date",
                label="Datum des Laufs",
                description="Lokales Kalenderdatum des Verlängerungslaufs.",
            ),
            EmailVariable(
                name="renewal_failures_html",
                label="Liste (HTML)",
                description=(
                    "Server-erzeugte, bereits escapte HTML-Liste der "
                    "fehlgeschlagenen Abos (Mitglied, Abo-Nummer, Grund). Als "
                    "``{{ renewal_failures_html }}`` in einer ``<ul>`` einfügen."
                ),
            ),
            EmailVariable(
                name="renewal_failures_text",
                label="Liste (Text)",
                description=(
                    "Text-Variante der fehlgeschlagenen Abos. Als "
                    "``{{ renewal_failures_text }}`` einfügen."
                ),
            ),
            EmailVariable(
                name="review_url",
                label="Link zur Abo-Verwaltung",
                description="Link zur Abo-Liste im Büro-Bereich.",
            ),
        ],
        sample={
            "tenant_name": "Beispiel-Solawi",
            "failure_count": "2",
            "run_date": "01.07.2026",
            "renewal_failures_html": (
                "<li><strong>Lukas Meyer</strong> (Mitglied #204) — Abo 17: "
                "Keine passende Anteils-Variante deckt die neue Laufzeit ab.</li>"
                "<li><strong>Anja Kern</strong> (Mitglied #88) — Abo 23: "
                "Der Verteilstationstag reicht nicht in die neue Laufzeit.</li>"
            ),
            "renewal_failures_text": (
                "- Lukas Meyer (Mitglied #204) — Abo 17: Keine passende "
                "Anteils-Variante deckt die neue Laufzeit ab.\n"
                "- Anja Kern (Mitglied #88) — Abo 23: Der Verteilstationstag "
                "reicht nicht in die neue Laufzeit."
            ),
            "review_url": "https://beispiel.example/abos/abos",
        },
    ),
    "commissioning.offer": EmailTemplateSpec(
        slug="commissioning.offer",
        label="Wochenangebot an Wiederverkäufer",
        description="Wird an Wiederverkäufer:innen gesendet, sobald ein neues Bestellformular freigegeben ist.",
        default_template="commissioning/emails/offer",
        default_subject="{{ tenant_name }}: Dein Angebot für {{ offer.period }}",
        default_subject_en="{{ tenant_name }}: Your offer for {{ offer.period }}",
        default_subject_fr="{{ tenant_name }} : votre offre pour {{ offer.period }}",
        default_subject_it="{{ tenant_name }}: la tua offerta per {{ offer.period }}",
        category="resellers",
        variables=[
            _TENANT_NAME,
            _RESELLER_NAME,
            EmailVariable(
                name="offer.period",
                label="Angebotszeitraum",
                description="Bezeichnung der Bestellperiode, z. B. 'KW 24 / 2026'.",
            ),
            EmailVariable(
                name="offer_url",
                label="Bestelllink",
                description="Direkter Link zum Bestellformular.",
            ),
        ],
        sample={
            "tenant_name": "Beispiel-Solawi",
            "reseller": {"name": "Bio Laden Müller"},
            "offer": {"period": "KW 24 / 2026"},
            "offer_url": "https://app.example.org/offer/2026-24",
        },
    ),
    "commissioning.invoice": EmailTemplateSpec(
        slug="commissioning.invoice",
        label="Rechnung",
        description="Wird mit der monatlichen/wöchentlichen Rechnung als PDF an Wiederverkäufer:innen gesendet.",
        default_template="commissioning/emails/invoice",
        default_subject="Rechnung {{ invoice.number }} — {{ tenant_name }}",
        default_subject_en="Invoice {{ invoice.number }} — {{ tenant_name }}",
        default_subject_fr="Facture {{ invoice.number }} — {{ tenant_name }}",
        default_subject_it="Fattura {{ invoice.number }} — {{ tenant_name }}",
        category="resellers",
        variables=[
            _TENANT_NAME,
            _RESELLER_NAME,
            _INVOICE_NUMBER,
            EmailVariable(
                name="invoice.period",
                label="Abrechnungszeitraum",
                description="Zeitraum, der mit dieser Rechnung abgerechnet wird.",
            ),
            _INVOICE_TOTAL,
            EmailVariable(
                name="invoice.due_date",
                label="Fälligkeitsdatum",
                description="Bis zu diesem Datum ist die Rechnung zu begleichen.",
            ),
            _TENANT_BANK,
        ],
        sample={
            "tenant_name": "Beispiel-Solawi",
            "reseller": {"name": "Bio Laden Müller"},
            "invoice": {
                "number": "2026-0042",
                "period": "Mai 2026",
                "total": "€ 1.234,56",
                "due_date": "30. Juni 2026",
            },
            "tenant": {"bank_details": "DE12 3456 7890 1234 5678 90 — GENODEF1XXX"},
        },
    ),
    "commissioning.delivery_note": EmailTemplateSpec(
        slug="commissioning.delivery_note",
        label="Lieferschein",
        description=(
            "Wird manuell vom Büro gesendet, "
            "wenn der Lieferschein als PDF vorab oder zur Abgleichung "
            "gewünscht ist. Der gedruckte Lieferschein begleitet die "
            "Ware in der Lieferkiste — die E-Mail ist optional und "
            "wird per Bestellzeile aus DeliveryNotes.tsx ausgelöst."
        ),
        default_template="commissioning/emails/delivery_note",
        default_subject="Lieferschein {{ delivery_note.number }} — {{ tenant_name }}",
        default_subject_en="Delivery note {{ delivery_note.number }} — {{ tenant_name }}",
        default_subject_fr="Bon de livraison {{ delivery_note.number }} — {{ tenant_name }}",
        default_subject_it="Bolla di consegna {{ delivery_note.number }} — {{ tenant_name }}",
        category="resellers",
        variables=[
            _TENANT_NAME,
            _RESELLER_NAME,
            EmailVariable(
                name="delivery_note.number",
                label="Lieferschein-Nummer",
                description="Vollständige Lieferschein-Nummer (Präfix-Nummer).",
            ),
            EmailVariable(
                name="delivery_note.date",
                label="Lieferschein-Datum",
                description="Datum, das auf dem Lieferschein steht.",
            ),
            EmailVariable(
                name="delivery_note.order_number",
                label="Bestellnummer",
                description="Bestellung, zu der dieser Lieferschein gehört (falls vorhanden).",
            ),
        ],
        sample={
            "tenant_name": "Beispiel-Solawi",
            "reseller": {"name": "Bio Laden Müller"},
            "delivery_note": {
                "number": "LS-2026-0042",
                "date": "12. Juni 2026",
                "order_number": "B-2026-0123",
            },
        },
    ),
    "gdpr.deletion_confirm": EmailTemplateSpec(
        slug="gdpr.deletion_confirm",
        label="Löschung bestätigen (DSGVO Art. 17)",
        description=(
            "Wird gesendet, nachdem jemand seine Daten löschen möchte. "
            "Enthält den 24-h-Bestätigungslink, der die Löschung dann "
            "tatsächlich auslöst."
        ),
        default_template="gdpr/emails/deletion_confirm",
        default_subject="Bitte bestätige die Löschung deiner Daten bei {{ tenant_name }}",
        default_subject_en="Please confirm the deletion of your data at {{ tenant_name }}",
        default_subject_fr="Veuillez confirmer la suppression de vos données chez {{ tenant_name }}",
        default_subject_it="Conferma la cancellazione dei tuoi dati presso {{ tenant_name }}",
        category="users",
        variables=[
            _TENANT_NAME,
            _USER_FIRST,
            EmailVariable(
                name="confirm_url",
                label="Bestätigungslink",
                description="Einmaliger 24-h-Link, der die Löschung auslöst.",
            ),
            EmailVariable(
                name="requires_admin_approval",
                label="Admin-Freigabe nötig?",
                description=(
                    "True, wenn das Büro nach der E-Mail-Bestätigung "
                    "die Löschung noch manuell freigeben muss."
                ),
            ),
        ],
        sample={
            "tenant_name": "Beispiel-Solawi",
            "user": {"first_name": "Maria"},
            "confirm_url": "https://app.example.org/gdpr/confirm-deletion/abc123",
            "requires_admin_approval": False,
        },
    ),
    "gdpr.deletion_approved": EmailTemplateSpec(
        slug="gdpr.deletion_approved",
        label="Löschung abgeschlossen (DSGVO Art. 17)",
        description=(
            "Wird gesendet, nachdem das Büro die Löschanfrage freigegeben "
            "und die Anonymisierung ausgeführt wurde."
        ),
        default_template="gdpr/emails/deletion_approved",
        default_subject="Deine Daten wurden bei {{ tenant_name }} gelöscht",
        default_subject_en="Your data has been deleted at {{ tenant_name }}",
        default_subject_fr="Vos données ont été supprimées chez {{ tenant_name }}",
        default_subject_it="I tuoi dati sono stati cancellati presso {{ tenant_name }}",
        category="users",
        variables=[_TENANT_NAME, _USER_FIRST],
        sample={
            "tenant_name": "Beispiel-Solawi",
            "user": {"first_name": "Maria"},
        },
    ),
    "gdpr.deletion_pending_admin_office": EmailTemplateSpec(
        slug="gdpr.deletion_pending_admin_office",
        label="Löschanfrage wartet auf Freigabe (Büro)",
        description=(
            "Push-Benachrichtigung an das Büro, wenn jemand seine "
            "DSGVO-Löschanfrage per E-Mail-Link bestätigt hat und die "
            "Anfrage damit in den Status ``PENDING_ADMIN`` übergeht. "
            "Geht an die allgemeine Büro-Mailbox (``Tenant.email``); "
            "ohne diese Mail würde das Büro die Anfrage erst sehen, "
            "wenn jemand die GDPR-Konfigurations-Seite öffnet."
            "\n\n"
            "**Bewusst PII-arm**: Die Mail enthält weder Namen noch "
            "E-Mail noch Mitgliedsnummer der antragstellenden Person — "
            "nur einen Link auf die Übersichts-Seite. Die Büro-Mailbox "
            "ist oft eine geteilte Inbox; jede zusätzliche PII dort "
            "wäre eine zweite Datenschutz-Fläche, die wir verwalten "
            "müssten."
        ),
        default_template="gdpr/emails/deletion_pending_admin_office",
        default_subject=("Neue Löschanfrage wartet auf Freigabe — {{ tenant_name }}"),
        default_subject_en="New deletion request awaiting approval — {{ tenant_name }}",
        default_subject_fr="Nouvelle demande de suppression en attente de validation — {{ tenant_name }}",
        default_subject_it="Nuova richiesta di cancellazione in attesa di approvazione — {{ tenant_name }}",
        category="office",
        variables=[
            _TENANT_NAME,
            EmailVariable(
                name="review_url",
                label="Link zur Freigabe-Seite",
                description=(
                    "Direkter Link auf ``/configuration/gdpr`` im "
                    "Büro-Frontend, wo die wartenden Anfragen "
                    "aufgelistet sind."
                ),
            ),
        ],
        sample={
            "tenant_name": "Beispiel-Solawi",
            "review_url": "https://app.example.org/configuration/gdpr",
        },
    ),
    "gdpr.deletion_rejected": EmailTemplateSpec(
        slug="gdpr.deletion_rejected",
        label="Löschung abgelehnt (DSGVO Art. 17)",
        description=(
            "Wird gesendet, wenn das Büro die Löschanfrage ablehnt — z. B. "
            "wegen offener gesetzlicher Pflichten. Enthält die vom Büro "
            "angegebene Begründung."
        ),
        default_template="gdpr/emails/deletion_rejected",
        default_subject="Deine Löschanfrage bei {{ tenant_name }} wurde abgelehnt",
        default_subject_en="Your deletion request at {{ tenant_name }} was declined",
        default_subject_fr="Votre demande de suppression auprès de {{ tenant_name }} a été refusée",
        default_subject_it="La tua richiesta di cancellazione presso {{ tenant_name }} è stata respinta",
        category="users",
        variables=[
            _TENANT_NAME,
            _USER_FIRST,
            EmailVariable(
                name="reason",
                label="Ablehnungsgrund",
                description="Vom Büro eingegebene Begründung, warum der Antrag jetzt nicht ausgeführt werden kann.",
            ),
        ],
        sample={
            "tenant_name": "Beispiel-Solawi",
            "user": {"first_name": "Maria"},
            "reason": "Es gibt noch 3 offene Genossenschaftsanteile, die zuerst gekündigt werden müssen.",
        },
    ),
    "commissioning.invoice_reminder": EmailTemplateSpec(
        slug="commissioning.invoice_reminder",
        label="Zahlungserinnerung",
        description=(
            "Konsolidierte Zahlungserinnerung an Wiederverkäufer:innen — "
            "EINE E-Mail pro Empfänger:in, die alle offenen Rechnungen "
            "aus dem Bulk-Versand auflistet. Wird über den Knopf "
            "'Erinnerungen versenden' auf der Zahlungs-Übersicht "
            "ausgelöst."
        ),
        default_template="commissioning/emails/invoice_reminder",
        default_subject="Zahlungserinnerung — {{ tenant_name }}",
        default_subject_en="Payment reminder — {{ tenant_name }}",
        default_subject_fr="Rappel de paiement — {{ tenant_name }}",
        default_subject_it="Sollecito di pagamento — {{ tenant_name }}",
        category="resellers",
        variables=[
            _TENANT_NAME,
            _RESELLER_NAME,
            EmailVariable(
                name="invoices_table",
                label="Tabelle offener Rechnungen",
                description=(
                    "Vorgefertigte HTML-Tabellenzeilen der überfälligen "
                    "Rechnungen (Nummer, Betrag, Ausstellungs-/Fälligkeitsdatum, "
                    "Tage überfällig). Einfach mit ``{{ invoices_table }}`` "
                    "innerhalb des ``<tbody>`` einfügen — keine Schleife nötig "
                    "(die sichere Vorlagen-Engine kann keine Schleifen)."
                ),
            ),
            EmailVariable(
                name="invoices_text",
                label="Liste offener Rechnungen (Text)",
                description=(
                    "Dieselbe Liste als Klartext, eine Zeile pro Rechnung — "
                    "für die Text-Variante der E-Mail. Mit "
                    "``{{ invoices_text }}`` einfügen."
                ),
            ),
            _TENANT_BANK,
        ],
        sample={
            "tenant_name": "Beispiel-Solawi",
            "reseller": {"name": "Bio Laden Müller"},
            "invoices_table": (
                "<tr><td><strong>2026-0042</strong></td><td>1234.56</td>"
                "<td>2026-05-01</td><td>2026-05-31</td><td>9 Tage</td></tr>"
                "<tr><td><strong>2026-0058</strong></td><td>612.30</td>"
                "<td>2026-05-08</td><td>2026-06-07</td><td>2 Tage</td></tr>"
            ),
            "invoices_text": (
                "- 2026-0042 (1234.56), ausgestellt am 2026-05-01, "
                "fällig am 2026-05-31 (9 Tage überfällig)\n"
                "- 2026-0058 (612.30), ausgestellt am 2026-05-08, "
                "fällig am 2026-06-07 (2 Tage überfällig)"
            ),
            "tenant": {"bank_details": "DE12 3456 7890 1234 5678 90 — GENODEF1XXX"},
        },
    ),
    "tenants.smtp_test": EmailTemplateSpec(
        slug="tenants.smtp_test",
        label="SMTP-Test (interne Konfiguration)",
        description=(
            "Wird bei 'Test-Versand' aus der E-Mail-Konfiguration "
            "(Einstellungen → SMTP) gesendet. Inhaltlich nur eine "
            "Bestätigung, dass die SMTP-Anbindung funktioniert. "
            "Wenn ihr den Text anpasst, gilt das nur für eure "
            "eigenen Test-Mails — er erscheint nirgendwo sonst."
        ),
        default_template="tenants/emails/smtp_test",
        default_subject="Jasmin – Test-E-Mail von {{ tenant_name }}",
        default_subject_en="Jasmin – test email from {{ tenant_name }}",
        default_subject_fr="Jasmin – e-mail de test de {{ tenant_name }}",
        default_subject_it="Jasmin – email di prova da {{ tenant_name }}",
        category="users",
        variables=[
            _TENANT_NAME,
        ],
        sample={
            "tenant_name": "Beispiel-Solawi",
        },
    ),
}


def get_spec(slug: str) -> EmailTemplateSpec:
    """Look up a template spec by slug. Raises KeyError if unknown."""
    return REGISTRY[slug]


def all_specs() -> list[EmailTemplateSpec]:
    """Return every registered template spec, ordered by category then slug."""
    order = {c: i for i, c in enumerate(CATEGORY_ORDER)}
    return sorted(
        REGISTRY.values(),
        key=lambda s: (order.get(s.category, len(CATEGORY_ORDER)), s.slug),
    )
