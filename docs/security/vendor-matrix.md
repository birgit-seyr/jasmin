# EU-friendly vendor matrix

A reference cheatsheet of EU-located vendors for each layer of a
hosted multi-tenant SaaS. Pick from this table when standing up
the security stack (see [`../todos/deploy.md`](../todos/deploy.md)
for the actual standup tasks).

This is **reference material, not a TODO** — it changes only when
the vendor landscape shifts. Last reviewed: 2026-06-06.

| What you need | EU options | Notes |
|---|---|---|
| **CDN + WAF + DDoS** | Bunny.net (SI), Gcore (LU), CDN77 (CZ), DataDome (FR — bot mgmt only, premium), OVHcloud (FR — basic, bundled with hosting) | Bunny is the cheapest, most beginner-friendly. |
| **Server hosting** | Linode (US, EU regions), Hetzner (DE), OVHcloud (FR), Scaleway (FR), IONOS (DE) | Hetzner is the EU-pure choice. |
| **Managed Postgres** | Hetzner Cloud DB (DE), Scaleway (FR), OVH Public Cloud DB | Or self-host on the same Linode/Hetzner box. |
| **Object storage (backups)** | Hetzner Storage Box, Scaleway Object Storage, OVH Object Storage, Bunny Storage | All S3-compatible. |
| **Error monitoring** | Sentry (self-hostable; sentry.io is US-hosted but EU region exists), GlitchTip (EU OSS hosted), self-hosted Sentry | Self-host on Hetzner for full EU control. |
| **Uptime monitoring** | Better Stack (EE/EU), Uptime Kuma (self-host), StatusCake (UK) | Uptime Kuma is free + self-host. |
| **Bot / Captcha** | Friendly Captcha (DE), HCaptcha (US but privacy-friendly), DataDome (FR) | Friendly Captcha is the EU pick (proof-of-work, cookieless). |

## Notes on selection

- **Cheapest viable EU starter stack:** Bunny.net (CDN + WAF) + Hetzner (host + DB + storage) + GlitchTip (error monitoring) + Uptime Kuma (uptime) + Friendly Captcha. All EU-located, all cookieless or DPA-friendly.
- **Procurement requires DPAs** — every vendor in this table needs an Art. 28 DPA on file. See [`../gdpr/avv-template.md`](../gdpr/avv-template.md) for the template and the deploy.md item to track signatures.
- **When to migrate off Linode:** if a customer asks for an EU-only data residency clause, the existing Linode-EU region passes Art. 44–49 in practice, but Hetzner / OVH / Scaleway are simpler to defend in DPIA paperwork.
