# Consent revocation — what actually happens

Reference for the "Revoke" action on the Member-detail consents card
(`MemberConsentsCard`). Traces the full effect of revoking a `ConsentRecord`,
the per-kind decisions, and the one UI gap found while documenting this.

Date: 2026-07-03

## Entry points

- **Frontend:** `src/features/members/components/MemberConsentsCard.tsx` — the
  "Revoke" button (only on `is_active` rows) → confirm modal (reason, ≤200
  chars) → `useCommissioningConsentsRevokeCreate`.
- **API:** `POST /consents/{id}/revoke/` — `ConsentRecordViewSet.revoke`
  (`apps/commissioning/viewsets/consents_viewsets.py`).
- **Service (the real logic):** `ConsentService.revoke(...)`
  (`apps/commissioning/services/consent_service.py`).

## What `ConsentService.revoke()` does

1. **Soft-revoke, never delete.** Stamps `revoked_at = now()`,
   `revoked_reason` (truncated to 200), `revoked_by`, and `save()`s only those
   fields. The row stays for the audit trail. Re-revoking a row raises
   `ConsentAlreadyRevoked` (`consent.already_revoked`).
2. **Refreshes the Member cache column for that kind** (`_sync_member_cache`):
   sets `Member.<kind>_consent` to the newest **still-active** record's
   `consented_at`, or **NULL** if none remain. Always recomputed from the DB so
   a concurrent revoke can't leave the cache pointing at a revoked row.
3. **Then a kind-specific consequence** (see the decision table).

All of the above runs inside one atomic block: a downstream handler failure
(e.g. the SEPA hook) rolls the revoke back.

## Per-kind decisions

The two maps that drive this live at the top of `consent_service.py`
(`_CACHE_FIELD_BY_KIND`, `_FLAG_ON_REVOKE`).

| Consent kind   | Member cache column set → NULL | Extra effect on revoke |
| -------------- | ------------------------------ | ---------------------- |
| **sepa**       | `sepa_consent`                 | `notify_sepa_mandate_revoked(member)` via the `apps.shared.sepa_mandate_hooks` seam → payments switches the member's `BillingProfile` **off SEPA** (stops the direct debit). Automated consequence, same atomic block. |
| **privacy**    | `privacy_consent`              | Flagged for office review: `Member.consent_withdrawn_at = now()` **and** the office is emailed (`mail_admins`, on-commit). **NOT** an automatic erasure. |
| **withdrawal** | `withdrawal_consent`           | Same office-review flag + email as privacy. |
| **terms**      | *(none — no cache column)*     | **Nothing on the Member.** Only the `ConsentRecord.revoked_at` changes. |

Rationale baked into the code:

- **SEPA** withdrawal (Art. 7(3)) must actually stop the debit, so it has an
  automated consequence.
- **privacy / withdrawal** are processing-legal-basis withdrawals → they need a
  **human** decision (processing may still rest on contract / GenG retention),
  so the member is flagged (`consent_withdrawn_at`) and the office emailed
  rather than anything being erased. The member stays flagged until they
  re-consent.
- **terms** has no legacy cache column and isn't flagged — revoking it is
  audit-only.

## Finding: the member-level effects are invisible in the UI

Revoking `privacy` / `sepa` / `withdrawal` **does** mutate the Member
(`*_consent` nulled, `consent_withdrawn_at` stamped, BillingProfile turned
off). `MemberConsentsCard` even invalidates the member-detail query on success,
expecting the UI to reflect it. But:

- `consent_withdrawn_at`, `sepa_consent`, `privacy_consent`,
  `withdrawal_consent` are all present on the generated `Member` type yet are
  rendered in **zero** frontend components.
- So the office gets an email + a DB flag, but there is **no on-screen signal**
  on the member that a consent-review is pending. From the office's point of
  view the member looks "completely unchanged" after a revoke.
- Revoking a **terms** consent genuinely leaves the Member row unchanged (by
  design) — so if that's what was revoked, "unchanged" is correct, not a bug.

**Recommendation:** surface the pending-review flag. When
`member.consent_withdrawn_at` is set, show a warning banner/tag on MemberDetail
(e.g. "⚠ Consent withdrawn on <date> — office review required"), and give the
office a way to clear the flag once reviewed. Frontend-only; the field is
already on the `Member` type. Optionally also show the `*_consent` timestamps
(or a simple consented/withdrawn status) so the cache columns are legible.
