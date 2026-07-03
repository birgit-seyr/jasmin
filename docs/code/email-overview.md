================================================================================
JASMIN EMAIL OVERVIEW
================================================================================
Last updated: 2026-06-04
Last audited: 2026-06-04 (see Section 7)

This file is the canonical reference for every email the platform sends:
trigger, recipient, sender, template, purpose. Use it when adding new email
flows so we keep the system coherent.

Status at a glance: Section 7 is the live progress tracker. As of
2026-06-04, ALL P0 ITEMS ARE CLOSED. Every send in the codebase
now goes through `EmailService.send_email` and lands in EmailLog;
the four UI columns that read tracker fields all show real state.

Bulk SMTP loops moved to Huey (2026-06-05):
`OfferService.bulk_send_offers_via_email` and the invoice-
reminder bulk send were both blocking the HTTP request for the
entire sequential SMTP loop (200–500 s worst case for 50–100
resellers). Both now enqueue a Huey-backed `BackgroundJob` and
return 202 + `{job_id}`; the React side polls
`GET /api/notifications/jobs/{id}/` via `useJob` and renders
progress + per-item results in a generic `JobProgressDrawer`.

Foundation (reusable for any future async work):

- `apps/notifications/models.py::BackgroundJob` — tenant-
  scoped, generic, holds `kind` + `status` + `progress` +
  `result`. Migration `notifications.0002_backgroundjob`.
- `apps/notifications/jobs.py` — `enqueue_job(kind, task,
task_kwargs, created_by)` does the create-row +
  on_commit-schedule dance in one call. Worker-side helpers:
  `mark_running` / `update_progress` / `mark_done` /
  `mark_failed`.
- Polling endpoint: `GET /api/notifications/jobs/<uuid>/`
  via `BackgroundJobViewSet` (read-only, IsOffice).

Migrated endpoints (steps 2 + 3):

- `BulkSendOffersViaEmailView` → enqueues
  `commissioning.tasks.run_bulk_offer_send` with kind
  `offer.bulk_send`. View now returns 202 in <100ms regardless
  of reseller count.
- `BulkSendInvoiceRemaindersViaEmailView` → enqueues
  `run_bulk_invoice_reminder_send` with kind
  `invoice_reminder.bulk_send`. Same 202 contract. The bulk
  logic was extracted to
  `apps/commissioning/services/invoice_reminder_service.py`
  so the task body has a clean entry point.

Tier 4+ (not migrated, per user direction): GDPR SAR, bulk
document creation, billing-run export, CSV exports — all
documented in the codebase audit but left synchronous for now.

Frontend pieces:

- `hooks/useJob.ts` — TanStack Query polling at 1.5 s,
  auto-stops on terminal status.
- `components/JobProgressDrawer.tsx` — generic drawer,
  renders progress bar + counters + per-item result table.
- `Offers.tsx` and `PaymentsResellers.tsx` capture the
  `job_id` from the 202 response and open the drawer;
  closing it triggers a table invalidation so freshly-stamped
  OfferSending rows show up immediately.

Tests adjusted: view tests now assert the 202+job contract;
SMTP-mocking + consolidation assertions moved to
`tests_services/test_invoice_reminder_service.py`.

Welcome / activation disambiguation (2026-06-04, post-P2-2):
`accounts.welcome` was renamed to `accounts.welcome_user`
and moved to category=`users`. The old name + label
("Willkommen Mitglied") + subject ("Willkommen bei …") read as
a second member-welcome on top of `accounts.application_
approved` — but the event is fundamentally USER-account
activation (fires for every account that goes `pending_
invitation → active`, including office and admin users, not
just members). Renaming makes the contract explicit; the
matching template files moved to `accounts/emails/welcome_
user.{de,en}.{html,txt}` and the two `.html` versions were
rewritten from the stale member-centric copy to the user-
centric copy the `.txt` files already had. Same pass also
tightened `accounts.application_approved`'s default subject
to "Willkommen als Mitglied bei {{ tenant_name }}!" so the
membership framing is unambiguous, and fixed a latent bug in
`MemberService.link_to_user` which dispatched the welcome
without `portal_url` (rendering a broken "Log in at ."
sentence). The three lifecycle emails now read cleanly:
application_approved → MEMBERSHIP admit
welcome_user → USER-account activation
trial_converted → GenG-MEMBERSHIP reached (first share)

Tracker-field consolidation (2026-06-04, post-P0-4): the
redundant boolean columns `has_been_sent_via_email` and
`has_been_sent_to_accounting` were dropped from
`InvoiceReseller` and `DeliveryNoteReseller` in migration 0019. Single source of truth is now the `*_at` timestamp;
`has_been_sent_to_reseller` and `has_been_sent_to_accounting`
are @property accessors that derive the boolean on read. The
serializers + view-layer aggregation rename the API field at the
same time:
delivery_note_has_been_sent_via_email
-> delivery_note_has_been_sent_to_reseller
invoice_has_been_sent_via_email
-> invoice_has_been_sent_to_reseller
The accounting pair already used the canonical naming; only the
reseller-side rename was needed for symmetry. Frontend pages
(Invoices.tsx, DeliveryNotes.tsx, PaymentsResellers.tsx) +
factories + GDPR SAR export all updated. Requires
`make generate-api` to refresh the orval client types.

Remaining P1 work is just P1-6 (waiting-list "spot available"
stamp-without-send), DEFERRED at user request 2026-06-04 because
the waiting-list logic itself is not done yet — revisit when that
ships. Everything else in P1 is closed: P1-1 not-applicable-by-
design; P1-2 + P1-5 closed 2026-06-04 with the OfferSending
composite-key reshape; P1-3 closed 2026-06-04 with the
on_commit-based atomicity policy across MemberService, the
invitation flow, and the public /register endpoint (GDPR stays
intentionally state-first because the underlying anonymisation is
irreversible); P1-4 closed 2026-06-04 by repurposing
EmailLog.provider_message_id to hold an RFC 5322 Message-ID
stamped on every outgoing message. Beyond P1 is the P2 list of
business-event emails (implement when product asks). The
architecture in Section 5 (webhook → status pipeline) is provider
-specific and DOES NOT APPLY to the SMTP-only deployment target;
`EmailLog.status` permanently stays `sent` / `failed` (SMTP
synchronous response only).

---

0. Architecture in 30 seconds

---

- Every outbound email goes through `EmailService.send_email(slug=..., ...)`
  in `apps/shared/tenants/email_service.py`.
- Per-tenant credentials live in `TenantEmailConfig` (encrypted, public schema).
- ONE sender per tenant by default (`from_email`), one Reply-To. All
  recipients see "From: Your Coop <noreply@...>" with replies routed to a
  real human inbox.
- TRANSPORT IS SMTP ONLY. Each tenant brings their own SMTP host
  (corporate Exchange, Strato / IONOS / mailbox.org / Posteo / Google
  Workspace, or self-hosted Postfix). No transactional-ESP layer
  (SendGrid / SES / Mailgun) is supported. The TenantEmailConfig model
  reflects this — it carries `smtp_host`, `smtp_port`, `smtp_username`,
  `smtp_password` (encrypted), `smtp_use_tls`. There is no `api_key`
  field and no provider selector. Earlier versions of this doc
  described a multi-provider architecture that was never built.
- One consequence of SMTP-only: no provider webhooks → no
  delivered / bounced / complained tracking. EmailLog.status is a
  binary `sent` / `failed` reflecting the synchronous SMTP response.
  Detailed treatment in Section 5.
- Templates live in two layers:
  1. SHIPPED DEFAULT — `.html` / `.txt` files inside each app's
     `templates/<app>/emails/` folder. Authored by us, rendered with the
     full Django template engine.
  2. TENANT OVERRIDE — `apps.notifications.EmailTemplate` (DB row). Edited
     by tenant admins via the React UI under
     `/configuration/email-templates`. Rendered with a SAFE Mustache-style
     renderer (`apps/notifications/template_renderer.py`) — only
     `{{ var.path }}` substitutions, no template tags, no filters.

---

1. Currently registered email templates

---

The single source of truth is `apps/notifications/registry.py`. Every
registered slug is editable by the tenant admin. App namespacing keeps
template files from colliding when Django merges them into one space.

Legend (Status column):
OK live, fires as documented, tracker (if any) is kept in sync
BROKEN registered + UI surfaces it, but production code path is wrong
(see Section 7 for the specific bug)
DEAD registered but no code anywhere sends it
EDGE fires only on a side path, not the canonical trigger you'd expect

| #   | Slug                           | Trigger                                                               | Recipient                   | Tracker (model.field — where the "we sent it" gets recorded)                                                     | Status |
| --- | ------------------------------ | --------------------------------------------------------------------- | --------------------------- | ---------------------------------------------------------------------------------------------------------------- | ------ |
| 1   | accounts.invitation            | Admin invites user (Configuration > Users / Members)                  | Invited user                | UserInvitation row (status=`sent`, before-send, in `@transaction.atomic`)                                        | OK     |
| 2   | accounts.password_reset        | User clicks "Forgot your password?"                                   | User                        | none (HMAC token, stateless) — EmailLog only                                                                     | OK     |
| 3   | accounts.application_received  | Public self-registration (/register)                                  | Applicant                   | none — EmailLog only                                                                                             | OK     |
| 4   | accounts.application_approved  | Office confirms a member application                                  | Applicant                   | Member.admin_confirmed_at (set by `confirm()`, not by the send)                                                  | OK     |
| 5   | accounts.application_rejected  | Office rejects a member application                                   | Applicant                   | Member.rejected_at (set by `reject()`, not by the send)                                                          | OK     |
| 6   | accounts.welcome_user          | User-account activated (invitation accepted)                          | Any user                    | none — EmailLog only                                                                                             | OK     |
| 7   | commissioning.offer            | Send weekly offer to reseller (bulk send)                             | Reseller                    | OfferSending row — but wrong-keyed + non-atomic, see P1-2                                                        | OK     |
| 8   | commissioning.invoice          | Auto-fired by `upload_pdf` after invoice finalize                     | Reseller + accounting_email | InvoiceReseller.has_been_sent_to_reseller_at + has_been_sent_to_accounting_at (booleans are derived @properties) | OK     |
| 9   | commissioning.invoice_reminder | Bulk dunning / payment reminder                                       | Reseller                    | none — see P1 for adding `last_reminder_sent_at` + `reminder_count`                                              | OK     |
| 10  | gdpr.deletion_confirm          | User requested account deletion — confirmation link                   | JasminUser                   | DeletionRequest row (token, lifecycle timestamps)                                                                | OK     |
| 11  | gdpr.deletion_approved         | Admin approved a deletion request                                     | requested_email             | DeletionRequest.executed_at (separate from the send)                                                             | OK     |
| 12  | gdpr.deletion_rejected         | Admin rejected a deletion request                                     | requested_email             | DeletionRequest.rejected_at (separate from the send)                                                             | OK     |
| 13  | commissioning.delivery_note    | Manual office-triggered "Send to reseller" button on a finalized DN   | Reseller                    | DeliveryNoteReseller.has_been_sent_to_reseller_at (has_been_sent_to_reseller is a derived @property)             | OK     |
| 14  | tenants.smtp_test              | Tenant admin clicks "Send test" in the SMTP configuration UI          | Configurable                | none — EmailLog only (purpose=`test:smtp`)                                                                       | OK     |
| 15  | commissioning.member_cancelled | Office records a member's GenG Austritt (`cancel_member_with_coop_shares`) | Cancelled member            | Member.cancellation_email_sent_at (stamped post-send by the dispatcher)                                          | OK     |

Default file paths (per slug, relative to each app's `templates/`):

accounts.invitation accounts/emails/invitation.html
accounts.password_reset accounts/emails/password_reset.html
accounts.application_received accounts/emails/application_received.html
accounts.application_approved accounts/emails/application_approved.html
accounts.application_rejected accounts/emails/application_rejected.html
accounts.welcome_user accounts/emails/welcome_user.html
commissioning.offer commissioning/emails/offer.html
commissioning.invoice commissioning/emails/invoice.html
commissioning.invoice_reminder commissioning/emails/invoice_reminder.html
commissioning.delivery_note commissioning/emails/delivery_note.<lang>.html
gdpr.deletion_confirm gdpr/emails/deletion_confirm.<lang>.html
gdpr.deletion_approved gdpr/emails/deletion_approved.<lang>.html
gdpr.deletion_rejected gdpr/emails/deletion_rejected.<lang>.html
tenants.smtp_test tenants/emails/smtp_test.html
(in apps/shared/tenants/templates/)
commissioning.member_cancelled commissioning/emails/member_cancelled.<lang>.html

Each `.html` has a matching `.txt` plain-text fallback.

The gdpr.\* templates and `commissioning.delivery_note` use a
`.<lang>.html` suffix convention (currently `.de.html` and `.en.html`
shipped) because the wording is locale-sensitive enough that
compliance-team review is easier with one file per language. The
other commissioning + accounts templates rely on Django's i18n
inside one file — both shapes are valid.

Adding a new template:

1. Pick a slug, e.g. `staff.shift_reminder`.
2. Drop `apps/staff/templates/staff/emails/shift_reminder.{html,txt}`.
3. Add an entry to `apps/notifications/registry.py` with label, default
   subject, default_template path, declared variables, and `sample` data
   for the preview.
4. Call `EmailService().send_email(slug="staff.shift_reminder", ...)`
   from your service code.
5. Add a row to the table above.

---

## 1a. Trigger map — where each email actually fires from

Three flavours of trigger:

ADMIN An office / admin user clicks a button in the React app and
a single send (or bulk send) goes out.
AUTO No human in the loop at the email-send moment. Cascaded
automatically by another action (file upload, model save,
state transition). The triggering action may itself be a
human click — but the office didn't choose to send the
email, it just happened.
USER The recipient (or someone acting as them) triggers their
own email — public registration, password reset, requesting
their own GDPR deletion. NOT admin-initiated.

For each slug: the React surface, the DRF endpoint that fires it, and
the Python entry point. "(no UI yet)" marks slugs whose wiring is in
place but no frontend page calls them — the service still works if
invoked directly, the email layer is just waiting on its UI.

=== ADMIN — fired by an office click in the React app ===

accounts.invitation
UI: Configuration → Users → "Invite user" (InviteUserModal),
OR Members → row → "Send invitation" (Members.tsx:565)
Endpoint: POST /api/commissioning/members/{id}/send_invitation/
(members case) + the InviteUserModal call path for
non-member invites
Backend: `MemberService.send_invitation` →
`apps/shared/invitations.py::create_user_with_invitation`
OR `resend_invitation` → `_send_invitation_email`

accounts.application_approved
UI: Members → row → "Confirm" (opens AdminConfirmation modal
via `useModalAdminConfirmationMembers`)
Endpoint: POST /api/commissioning/members/{id}/confirm/
Backend: `MembersViewSet.confirm` →
`MemberService.confirm_and_notify`

accounts.application_rejected
UI: (no UI today) — backend wiring is complete
(`MemberService.reject_and_notify` is on_commit-safe,
the email template ships in both languages, and the
generated orval hook `useCommissioningMembersRejectCreate`
exists) but no React surface imports the hook. Office
can confirm a member but not reject one from the UI.
Endpoint: POST /api/commissioning/members/{id}/reject/
Backend: `MembersViewSet.reject` →
`MemberService.reject_and_notify`

commissioning.offer
UI: Offers → "Send to resellers" bulk action (Offers.tsx:676,
`commissioningBulkSendOffersViaEmailCreate`)
Endpoint: POST /api/commissioning/bulk_send_offers_via_email/
Backend: `BulkSendOffersViaEmailView` →
`OfferService.bulk_send_offers_via_email` (per-reseller
loop, OfferSending composite-key idempotency from P1-2)

commissioning.delivery_note
UI: DeliveryNotes → row action "Per E-Mail an Reseller"
button (DeliveryNotes.tsx, only visible on finalized +
not-yet-sent DNs with a reseller email on file)
Endpoint: POST /api/commissioning/delivery_notes/{id}/send_to_reseller/
Backend: `DeliveryNoteResellerViewSet.send_to_reseller` →
`DeliveryNoteService.send_to_reseller` (P0-3 — explicitly
manual, NOT auto on upload_pdf; paper still rides in
the box)

commissioning.invoice_reminder
UI: PaymentsResellers → bulk reminder action
(PaymentsResellers.tsx:330,
`commissioningBulkSendInvoiceRemaindersViaEmailCreate`)
Endpoint: POST /api/commissioning/bulk_send_invoice_remainders_via_email/
Backend: `BulkSendInvoiceRemaindersViaEmailView`

gdpr.deletion_approved
UI: Configuration → GDPR → PendingDeletionsCard → "Freigeben"
(PendingDeletionsCard.tsx:154,
`useGdprAdminApproveDeletionCreate`)
Endpoint: POST /api/gdpr/admin/approve_deletion/{request_id}/
Backend: `gdpr_admin_approve_deletion_view` →
`send_deletion_approved_email` (state-first, best-
effort — irreversible state change, see P1-3 GDPR note)

gdpr.deletion_rejected
UI: Configuration → GDPR → PendingDeletionsCard → "Ablehnen"
opens a reason modal (ConfigurationGDPR.tsx,
`useGdprAdminRejectDeletionCreate`)
Endpoint: POST /api/gdpr/admin/reject_deletion/{request_id}/
Backend: `gdpr_admin_reject_deletion_view` →
`send_deletion_rejected_email`

tenants.smtp_test
UI: Configuration → E-Mail → "Send test" button
(ConfigurationEmail.tsx:157, `sendTestEmail`)
Endpoint: POST /api/tenants/email-config/test/
Backend: `TenantEmailConfigViewSet.test_email` (P0-4 — routes
through EmailService so the test send lands in EmailLog
like any real send)

=== AUTO — cascades from another action, no separate "send" button ===

commissioning.invoice
Triggered by:
Office finishes invoice → frontend renders PDF (and the
ZUGFeRD XML) → uploads via
POST /api/commissioning/invoices/{id}/upload_pdf/
(generateInvoicePDF.tsx:227, called from Invoices.tsx).
The upload action wraps the file-save in
`transaction.atomic` and schedules two `on_commit`
dispatches: one to the reseller, one to
`TenantEmailConfig.accounting_email` (DATEV inbox).
Sampled BEFORE the save so a re-upload (PDF replace)
does NOT re-fire — re-send is currently NOT a separate
admin action.
Endpoint: POST /api/commissioning/invoices/{id}/upload_pdf/
Backend: `InvoiceResellerViewSet.upload_pdf` →
`InvoiceService.send_to_reseller` +
`InvoiceService.send_to_accounting`

TODO: commissioning.trial_converted
Triggered by:
Any code path that creates the FIRST CoopShare for a
trial member — `CoopShare.save()` (on insert) calls
`convert_trial_member_on_first_coop_share`, which
schedules the welcome via `on_commit`. Today that's
the office creating a CoopShare on the member detail
page; same flow fires for any future CoopShare-
creation surface.
Endpoint: whatever endpoint created the CoopShare (typically
POST /api/commissioning/coop_shares/)
Backend: `CoopShare.save` →
`convert_trial_member_on_first_coop_share` →
`_send_trial_converted_email`

accounts.welcome_user
Triggered by:
Invited user clicks the link in their `accounts.
               invitation` email, lands on /set-password/:token
(SetPasswordPage), submits the password form. Backend
flips `account_status → active` and schedules the
welcome via `on_commit`. Also fires from
`MemberService.link_to_user` when an office-created
Member is auto-linked to an already-active JasminUser
(edge case).
Endpoint: the accept-invitation POST (/set-password submit)
Backend: `accept_invitation` → `_send_welcome_email`

TODO: commissioning.member_cancelled
Triggered by:
`cancel_member_with_coop_shares`. Currently called ONLY
from `apps/gdpr/services.py::_anonymize_member`, which
scrubs `member.email = None` BEFORE calling the
service — so the email guard skips and no actual send
happens on the GDPR path. The wiring is in place for
a future "Office records an Austritt" UI; once that
surface ships, the email + tracker stamp will fire
automatically with no service-layer change.
Endpoint: (no UI yet) — only the GDPR anonymisation flow today
Backend: `cancel_member_with_coop_shares` →
`_send_cancellation_email`

=== USER — fired by the recipient or someone acting as them ===

accounts.password_reset
UI: Login → "Forgot your password?" → ForgotPasswordPage
submits email. Backend returns 200 either way to avoid
leaking which addresses are registered.
Endpoint: POST /api/auth/password-reset/
Backend: `password_reset_service.send_password_reset_email`

accounts.application_received
UI: Public /register form (auth/registration/Step1…Step6),
submitted from Step7Done. Sent to anyone who completes
the public membership-application wizard.
Endpoint: POST /api/auth/register/
Backend: `register_public_applicant`

gdpr.deletion_confirm
UI: User profile (top-right menu) → "Meine Daten" tab →
"Daten löschen" → `UserProfileModal.handleRequestDeletion`.
The user requests their own deletion; this email
carries the 24h confirmation link that actually
triggers the anonymisation.
Endpoint: POST /api/gdpr/request_deletion/
Backend: `gdpr_request_deletion_view` →
`send_deletion_confirmation_email`

Summary by category:

ADMIN-triggered: 8 (invitation, application_approved,
application_rejected, offer, delivery_note,
invoice_reminder, gdpr.deletion_approved,
gdpr.deletion_rejected, tenants.smtp_test)
AUTO-cascading: 4 (invoice, trial_converted, welcome_user,
member_cancelled — last is wired but currently
only reached by GDPR which scrubs email first)
USER-triggered: 3 (password_reset, application_received,
gdpr.deletion_confirm)

Total registered slugs: 16 (the 15 listed + the additional
`accounts.application_received` USER row counted here)

---

2. Sender configuration (TenantEmailConfig)

---

The actual model fields (as of 2026-06-04) are:

SMTP transport (host the tenant's mail goes through):
smtp_host mail.strato.de (or imap.ionos.de, mail.coop.de, ...)
smtp_port 587 (STARTTLS) or 465 (TLS)
smtp_username office@coop.de (often equals from_email)
smtp_password **\*\*\*\*** (EncryptedCharField; transparent at the
ORM layer, ciphertext on disk)
smtp_use_tls True

Sender identity (what recipients see in their inbox):
from_email noreply@mail.coop.de (envelope-from + From header)
from_name Coop Wien (display name)
reply_to_email office@coop.de (where humans' replies land)
accounting_email buchhaltung@coop.de (DATEV inbox, internal)

Operational:
max_emails_per_hour 1000 (soft rate-limit hook; not enforced
in code today)
is_active True (gate; if False, all sends short-circuit
with a log line, no SMTP attempt)
is_verified False -> True (flipped to True when a "Send test"
via TenantEmailConfigViewSet.test_email
actually delivers to localhost SMTP)

ONE sender is enough. You do NOT need separate "customers@" / "members@"
senders — the slug + template + reply_to combination is what differentiates
flows. Most coops will use a single noreply@... sender for everything and
let reply_to_email route human replies to office@.

If you ever want separate visible senders for cosmetic reasons (e.g. an
"invoices@" address on dunning mail), that's a future field add — none
of the current send sites care which address goes out.

---

3. DNS authentication — what the tenant must do (one-time)

---

The sending domain (the part after the @ in from_email) needs THREE DNS
records so Gmail / Outlook trust the mail and don't drop it in spam.
These records authenticate the DOMAIN, not the transport, so they're
needed equally with SMTP-only or any ESP — the only thing that changes
is what string goes inside.

Where: at the tenant's DNS host (Strato, IONOS, Cloudflare, GoDaddy,
hetzner-DNS, ...). NOT in their email inbox. NOT in our app. It does
NOT touch their normal mailboxes — info@coop.de in Outlook keeps
working as before.

SPF TXT record listing every server allowed to send AS this domain.
The values come from the tenant's MAIL PROVIDER, not from us.
Examples by provider:
Strato: v=spf1 include:\_spf.strato.de -all
IONOS: v=spf1 include:\_spf-eu.ionos.com -all
mailbox.org: v=spf1 include:\_spf.mailbox.org -all
Google Workspace: v=spf1 include:\_spf.google.com -all
Self-hosted SMTP: list the server's static IP(s):
v=spf1 ip4:203.0.113.10 -all
If the tenant already sends mail from this domain via the same
provider, the SPF record is probably already correct — no
change needed.

DKIM Public key (CNAME or TXT) so the provider can sign each outgoing
mail. Every provider has its own DKIM setup page in their admin.
Examples by provider:
Strato: one CNAME named e.g. `strato._domainkey.coop.de`
IONOS: CNAME `dkim1._domainkey.coop.de` ->
`dkim1.<account>.ionos.email`
mailbox.org: TXT `mbo._domainkey.coop.de` with the public key
they generate
The provider's dashboard tells the tenant exactly what to paste.

DMARC Tells receivers what to do if SPF/DKIM fail; collects reports.
Provider-agnostic. Same record regardless of who you send through.
Start: v=DMARC1; p=none; rua=mailto:dmarc@coop.de
Later: v=DMARC1; p=quarantine; rua=mailto:dmarc@coop.de
Final: v=DMARC1; p=reject; rua=mailto:dmarc@coop.de

The tenant pastes the SPF + DKIM records into their DNS panel.
Verification: send a test email to `check-auth@verifier.port25.com`
and read the bounce-back report, or use Google Postmaster Tools /
mxtoolbox.com for an interactive check.

Once verified, set `TenantEmailConfig.is_verified = True` (the
`TenantEmailConfigViewSet.test_email` action does this automatically
when a localhost-SMTP test succeeds — though that's a transport check,
not a DKIM check, so DNS verification has to be done separately by the
tenant).

Without these records, password-reset and invitation emails will land
in spam — full stop. The is_verified flag is informational; it does NOT
gate sends. Sends will go out even from an unverified config; they just
won't reach the recipient's inbox.

How hard is this in practice (rough buckets):

EASY (~30 min) Tenant already uses Strato/IONOS/Google Workspace
/Office 365/mailbox.org for their mail. SPF likely
already correct. DKIM is one CNAME from the
provider's dashboard. DMARC is one TXT. They log
in, paste 3 records, done.

ANNOYING(1–3 hr) Split-brain setup: domain at one registrar, mail
at another, marketing site at a third. Records
sometimes land in the wrong zone the first time.

HARD (multi-day) Tenant uses a small or legacy provider with no
DKIM support, or runs a non-technical org where
"DNS" is alien terminology. SMTP-only deliverability
becomes a real blocker — they can't ship without
help.

Hosted-email-as-a-service for the HARD bucket: NOT ON THE ROADMAP.
We considered offering Jasmin-hosted mail per tenant (Jasmin runs the
SMTP infra, tenants get `coop@mail.jasmin.app` or a delegated subdomain).
Decided against:

- Becoming an email provider means IP warmup, blacklist monitoring,
  abuse handling, GDPR data-processor liability per tenant, and
  ongoing per-mail costs.
- One compromised tenant account spamming → our IP gets blacklisted →
  every tenant's deliverability suffers.
- The product position is: if a tenant can't manage DNS for their
  own domain, they likely don't have the operational maturity to
  run a CSA. Jasmin is not a beginner-mode SaaS.
  Hard line. Don't re-open this in a future audit without a strong
  external trigger.

Mitigation for the EASY case: write per-provider DNS walkthroughs with
screenshots. Turns "30 min and unsure" into "30 min and confident". A
tenant onboarding wiki, not a code change.

---

4. Tenant-editable templates — model, registry, renderer

---

Why DB-stored on top of file-based defaults?

- Tenant admins must be able to tweak wording without a code deploy.
- We must keep our defaults in git so engineers can ship improvements.
- Customized tenants must NOT be overwritten by future shipped changes.

Hybrid design:

apps/notifications/registry.py Slug -> {label, default_subject,
default_template path,
variables, sample}.
Single source of truth.

apps/notifications/models.py EmailTemplate(slug, subject,
body_html, body_text,
is_customized,
updated_by, updated_at)
— TENANT-SCOPED row created lazily
when admin saves a customization.

apps/notifications/template_renderer Safe Mustache renderer: only
`{{ var.path }}` substitutions,
HTML-escaped by default, no `{% %}`,
no filters.

EmailService resolution order in `_resolve_template`:

1. `slug` + customized DB row exists -> render via Mustache renderer.
2. `slug` + no customization -> render the default `.html` file
   via Django (full power).
3. `template_name=` (legacy) -> render the raw path via Django.

REST API (under `/api/notifications/email-templates/`):

GET / List every registered template.
GET /<slug>/ Retrieve current effective subject + body + default versions + declared variables.
PATCH /<slug>/ Save tenant override (sets
`is_customized=True`).
POST /<slug>/reset/ Drop the override (revert to ship default).
POST /<slug>/preview/ Render with sample data; honours unsaved
edits posted in the body. Returns
{subject, html, text}.
POST /<slug>/test_send/ Send a real email to the requesting user
(or `recipient` from the body).

Frontend: `pages/configuration/ConfigurationEmailTemplates.tsx` — list +
edit modal with React Quill rich-text editor, "Insert variable" picker
backed by the registry, live preview pane, "Send test" button.

Note: every slug listed in Section 1 is editable through this UI today.

---

5. Observability — EmailLog (tenant-scoped, GDPR-conformant)

---

Lives in `apps.notifications.EmailLog`, which is a TENANT_APP — meaning the
`email_log` table is created inside each tenant's Postgres schema. There is
NO `tenant` FK; isolation is enforced by the schema itself.

Why tenant-scoped (not shared/public):

- Recipient address + subject are personal data (GDPR Art. 4).
- `DROP SCHEMA tenant_x CASCADE` automatically erases all email logs of a
  deleted tenant (GDPR Art. 17 / right to erasure).
- Cross-tenant SELECT is physically impossible — the table only exists
  in the tenant's own schema.
- TenantEmailConfig (provider credentials) stays in `public` because
  django-tenants needs access to it before activating any schema.

Each row tracks:

recipient | template (slug) | subject | status | provider_message_id | created_at

Status terminus is `sent` or `failed`. The transitions are:

new -> sent Tenant's SMTP server accepted the message
synchronously (250 OK on the DATA command).
new -> failed SMTP server rejected synchronously (connection
refused, bad credentials, recipient rejected
at RCPT TO, message size limit, ...).

There are NO further transitions. SMTP has no callback channel — once
the message leaves the tenant's SMTP server, Jasmin cannot observe
whether it reached the recipient's mailbox, was filtered to spam,
bounced asynchronously hours later, or got the user to mark it as
junk. That's the cost of SMTP-only; the benefit is zero dependence on
an external ESP and no per-mail third-party billing.

Field shape vs. transport reality:

EmailLog.provider_message_id Currently unused under SMTP-only. Could
be repurposed to store the RFC 5322
Message-ID stamped on each outgoing
mail so that if you later parse inbound
bounce DSNs (RFC 3464) from a
bounces@ mailbox, you can correlate
them back to the original send. Out of
scope today.
EmailLog.delivered_at Permanently null in this architecture.

Header still stamped for ops:

EmailService stamps every outgoing mail with
`X-Jasmin-Log-Ids: <comma-separated EmailLog.id list>`
(email_service.py:255). Useful as a breadcrumb in the tenant's own
mailserver logs — when a tenant's mail admin says "I see a 451 in my
Postfix queue for these IDs", you can grep EmailLog.

What you CAN answer today:

- "Did EmailService accept and hand off Maria's invitation?" — yes,
  query EmailLog where recipient=... AND status=sent.
- "Did the SMTP layer error out?" — yes, query EmailLog where
  status=failed (the error string is in the log row).
- "Did it actually reach Maria's inbox?" — NO. Ask Maria, or check
  the tenant's mail-server logs directly.

What you CANNOT answer today (would require inbound DSN parsing):

- Async bounces ("user@example.com left the company three months ago,
  mailbox removed last week").
- Complaints ("Maria's Gmail user marked us as spam").
- Soft deferrals ("Gmail rate-limited, will retry").

If async bounce visibility ever becomes business-critical (e.g. for
member-roster hygiene), the lightweight path is:

1. Configure the SMTP envelope-from address to bounces@tenantcoop.de.
2. Add a Huey periodic task that polls that mailbox via IMAP, parses
   the DSN bodies (Python's `email` stdlib does this), matches the
   `In-Reply-To` / `References` headers (or our stamped
   `X-Jasmin-Log-Ids`) back to EmailLog rows, and updates status.
   This is a moderate piece of work — DSN bodies are messy in practice —
   and is NOT currently planned.

---

7. Audit & fix backlog

---

Last audited: 2026-06-04.

This section is the live progress tracker. Each item is a discrete fix.
Tick the box (replace `[ ]` with `[x]`) and append the resolution date +
commit hash when done; never silently delete a closed entry — historical
context is what makes the next audit faster.

Priority key:
P0 silently broken in production: UI lies OR code that should send
doesn't OR trackers exist that nothing populates.
P1 structural gap: wrong-shape model, missing transaction wrapping,
infrastructure that the rest of the system assumes exists.
P2 business event that should plausibly notify but doesn't.
Implement when the product asks for it, not preemptively.

============================ P1 — structural gaps ==============================

[ ] P1-6 Waiting-list "spot available" stamps but doesn't send
apps/commissioning/models/mixin.py:949 `notify_spot_
          available()` flips status to SPOT_AVAILABLE and stamps
`notification_sent_at` — without dispatching an email
anywhere. The method also has no callers in non-test code.
Two options:
A) wire a `members.waiting_list_spot_available` slug + a
real caller from the vacancy-detection service;
B) delete the method + field as dead code.
Pick one. (Also listed as P2-9 in case the email gets built
for product reasons; P1 entry is about the misleading
"we did something" timestamp.)

======================== P2 — missing business-event emails ===================

Each row is a candidate flow. Implement when the product asks for it.

[ ] P2-4 members.subscription_cancelled
Event: SubscriptionService.cancel_subscription
(apps/commissioning/services/subscription_service.py:139)
Tracker: none — add subscription_cancellation_email_sent_at

[ ] P2-5 payments.sepa_mandate_signed
Event: BillingProfile save with sepa_mandate_signed_at
(apps/payments/models.py:60)
Tracker: sepa_mandate_signed_at exists; add email-sent flag

[ ] P2-6 payments.charge_schedule_issued (SEPA pre-notification)
Event: BillingRunService runs; each ChargeSchedule needs
a 5-banking-day pre-notification by SEPA rule.
Hard requirement, not optional, before any
production SEPA collection.
Tracker: ChargeSchedule status flow

[ ] P2-7 members.coopshare_issued / members.coopshare_repaid
Event: CoopShareService (issue + repay flows)
Tracker: none — add to CoopShare

[LATER] P2-8 commissioning.payment_received on InvoiceReseller.mark_paid
Event: InvoiceReseller.mark_paid
(apps/commissioning/models/resellers.py:966)
Tracker: paid_at exists
Note: not done for now

[LATER] P2-9 members.waiting_list_spot_available
Linked to P1-6. If P1-6 option A is chosen, this is the slug.
