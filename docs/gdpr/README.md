# GDPR docs

Audience: DPO, auditor, regulator, you-in-6-months when someone
asks "where do we stand on Art. X?".

## By GDPR article

| Article | What it requires | File |
|---|---|---|
| **Art. 5** | Lawfulness, minimisation, accuracy, storage limit | [`data-inventory.md`](data-inventory.md), [`retention-policy.md`](retention-policy.md) |
| **Art. 6, 7** | Legal basis + withdrawal of consent | (implementation: `ConsentDocument` / `ConsentRecord` models, `apps/commissioning/services/consent_service.py`) |
| **Art. 13, 14** | Information given to data subjects (privacy policy) | *Privacy policy is operational — see [`../todos/deploy.md`](../todos/deploy.md)* |
| **Art. 15** | Right of access (SAR / data export) | (implementation: `apps/gdpr/views.py` → `/api/gdpr/my-data/`) |
| **Art. 17** | Right to erasure | [`deletion-roadmap.md`](deletion-roadmap.md) |
| **Art. 25** | Data protection by design + by default | (cross-cutting — see [`../security/auth-reference.md`](../security/auth-reference.md), [`../security/logging-overview.md`](../security/logging-overview.md)) |
| **Art. 28** | Sub-processor contracts (DPA / AVV) | [`avv-template.md`](avv-template.md) |
| **Art. 30** | Records of processing activities (VVT) | [`processing-activities.md`](processing-activities.md) |
| **Art. 32** | Security of processing | [`../security/`](../security/) |
| **Art. 33, 34** | Breach notification (72h) | [`breach-runbook.md`](breach-runbook.md) |
| **Art. 35** | Data Protection Impact Assessment (DPIA) | [`dpia-assessment.md`](dpia-assessment.md) |
| **Art. 5(1)(e) + DSGVO §§ 257 HGB / 147 AO** | Retention | [`retention-policy.md`](retention-policy.md) |

## Review cadence

| File | Next review |
|---|---|
| `data-inventory.md` | Annual (next: see header) |
| `retention-policy.md` | Annual |
| `processing-activities.md` | Annual + on any vendor change |
| `breach-runbook.md` | Annual + after any drill |
| `dpia-assessment.md` | On any "high risk" scope change |
| `deletion-roadmap.md` | Per-step as the roadmap advances |
| `avv-template.md` | Annual (legal text + vendor list) |
