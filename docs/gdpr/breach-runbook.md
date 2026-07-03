# Data Breach Notification Runbook

**Legal basis:** GDPR Art. 33 (notify supervisory authority within
72h) and Art. 34 (notify affected data subjects if high risk).
**Status:** Operational runbook — must exist BEFORE a breach happens.
**Last reviewed:** 2026-06-02

A "personal data breach" under Art. 4(12) is any breach of security
leading to **accidental or unlawful destruction, loss, alteration,
unauthorised disclosure of, or access to** personal data. This
covers ransomware, lost laptops, mis-sent emails, leaked backups,
exposed S3 buckets, an SQL injection on the platform, an office
account being phished — anything that puts member data outside the
tenant's intended boundary.

---

## 0. Pre-incident setup (do this NOW)

- Named **incident lead** on file: [fill in]
- Named **data-protection contact**: [fill in]
- Supervisory authority: [fill in — typically the state DPA
  (Landesdatenschutzbehörde) where the tenant is registered]
- Authority's online breach-report form bookmark: [fill in]
- This runbook printed + filed offline (in case the platform itself
  is the incident)

---

## 1. Detect (T+0)

Likely detection paths:

- Sentry alert on an unexpected access pattern
- `django-axes` lockout spike
- Office staff notices content that should not be visible (e.g.
  one tenant's data leaking into another tenant's schema view)
- Backup verification failure
- External notification (a member, a sub-processor, a researcher)

Anyone noticing a potential breach **must** notify the incident
lead within 1 hour. Do not investigate alone, do not delete
evidence, do not "wait until it's confirmed before raising the
flag" — the 72-hour clock has already started.

---

## 2. Triage (T+0 to T+4h)

Incident lead convenes. Establish the facts:

| Question                                            | Answer |
|-----------------------------------------------------|--------|
| What data is involved? (categories + estimated rows)|        |
| How was it exposed?                                 |        |
| When did the exposure start?                        |        |
| When did the exposure end? (or is it ongoing?)      |        |
| Who has accessed the data?                          |        |
| Could the exposure result in harm to the members?   |        |
| Is the platform still vulnerable right now?         |        |

If still vulnerable → contain before anything else. Pull the
gateway, rotate credentials, revoke leaked tokens, kill the
exposed container. Loss of availability is preferable to ongoing
exposure of PII.

---

## 3. Notify the supervisory authority (T+72h hard deadline)

Art. 33 obliges notification **within 72 hours of becoming aware**
of a breach, unless the breach is unlikely to result in a risk
to the rights and freedoms of natural persons.

The threshold for "no risk" is genuinely low — when in doubt,
notify. The supervisory authority is generally lenient with
controllers that over-report; they are not lenient with controllers
that hide.

### Required content (Art. 33(3))

- Nature of the breach
- Categories + approximate number of data subjects affected
- Categories + approximate number of records affected
- Likely consequences
- Measures taken or proposed to address the breach and mitigate
  effects
- Name + contact of the DPO or data-protection contact

### How to file

- Most German Landesdatenschutzbehörden have an online form. Use
  the one for the state where the tenant is registered.
- BfDI fallback form fields are a good reference if the state form
  is offline: https://www.bfdi.bund.de/ → "Datenpannen melden".
- Save the submission confirmation PDF.

### If you miss 72 hours

File anyway. Include a justification for the delay (Art. 33(1)
sentence 2). Late filing is a separate, smaller offence than not
filing at all.

---

## 4. Notify affected data subjects (Art. 34)

Required when the breach is **likely to result in a high risk** to
the rights and freedoms of the affected individuals. High risk
includes:

- Financial data exposed (IBAN + account_owner is a high-risk pair)
- Authentication credentials exposed
- Combinations that enable identity fraud (name + birth_date +
  address + email)
- Data that could enable physical harm or discrimination

### Notification content

- Plain language, no legalese
- Nature of the breach
- DPO / data-protection contact
- Likely consequences
- Measures taken
- Recommendations for the affected person (e.g. change password,
  monitor bank statements, watch for phishing)

### Channel

- Email to the address on file is typically sufficient
- Use the existing Anymail transactional path (see
  `apps/notifications/`) so the send is logged
- If email itself is the breach surface, fall back to postal
  letter or a banner on the public privacy-policy page

### Exceptions (Art. 34(3))

Notification is NOT required if:
- The data was encrypted with state-of-the-art encryption AND the
  key was not compromised
- Subsequent measures have made the high risk no longer likely to
  materialise
- Notification would require disproportionate effort (then a
  public communication is required instead)

---

## 5. Document in the breach register (Art. 33(5))

The register is required **regardless of whether the breach was
notifiable**. One row per incident.

Suggested format: a markdown file at
`docs/gdpr/breach-register.md` (gitignored if the repo is
shared, kept under access control by the office).

Per-row schema:

```
| Date detected | Date occurred | Detection path | Data categories | Subjects affected | Notified DPA? | Notified users? | Resolution | Lessons |
```

Each row is immutable once written. Corrections go in a new row
with a `correction-of: <date>` annotation.

---

## 6. Containment & remediation

In parallel with notification:

- Patch the underlying vulnerability
- Rotate all credentials that may have been exposed
  (`DJANGO_SECRET_KEY`, `FIELD_ENCRYPTION_KEY`,
  SMTP passwords, DB passwords, JWT signing key)
  — see the `FIELD_ENCRYPTION_KEY` rotation runbook in
  `docs/code/engineering-audit-playbook.md`
- Force-logout all sessions (rotate JWT signing key + bump
  `RefreshToken` blacklist)
- If member-facing credentials may have been exposed, trigger
  password resets

---

## 7. Post-mortem (T+2 weeks)

Once contained:

1. Write a blameless post-mortem covering: timeline, root cause,
   what worked, what didn't, action items.
2. Convert action items into tracked tickets.
3. Update this runbook if any step was unclear or missing during
   the incident.
4. Append a row to the review schedule below.

---

## 8. Review schedule

| Date       | Reviewer       | Notes                          |
|------------|----------------|--------------------------------|
| 2026-06-02 | Initial draft  | Drawn up before first prod ship|
