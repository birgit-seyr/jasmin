# Security policy

Jasmin holds the personal data of farm members: names, addresses, and the bank
details their direct debits run on. Reports of security problems are welcome,
and we're grateful for every one of them.

## Reporting a vulnerability

Please **don't open a public issue, discussion or pull request** for a security
problem. Report it privately through GitHub instead: on the repository's
**Security** tab choose **Report a vulnerability**, or go straight to
<https://github.com/birgit-seyr/jasmin/security/advisories/new>. Only the
maintainer sees the report.

A short note is enough. It helps to include:

- what an attacker can do, and with which access — none, a member login, an
  office login, or an admin of another farm;
- the steps to reproduce it, ideally against a local copy;
- the commit, endpoint or page it affects;
- a suggested fix, if you have one.

## What happens next

We confirm your report as soon as we can, tell you whether we can reproduce it
and how severe we rate it, and keep you posted while we work on it. The most
severe problems are fixed first. Jasmin is a small project, so we can't promise
fixed response times.

Once the fix runs on the hosted platform, we publish a GitHub security advisory
and credit you, by name or handle, unless you'd rather stay anonymous.

Please keep the problem to yourself until the advisory is out. If a fix takes
long, we agree on a disclosure date with you.

## Supported versions

Jasmin has no versioned releases. Fixes land on `main`, and the hosted platform
is deployed from it.

| Version | Security fixes |
| ------- | -------------- |
| `main` | yes |
| any older commit | no — update to the latest `main` |

If you run your own copy, keep it on the latest `main`.

## Testing rules

- **Test against your own copy, never the hosted platform.** The hosted
  instances hold real farms' member data. The [quickstart](README.md#quickstart)
  sets up a local copy with a demo farm and a login for every role in a few
  minutes.
- If you come across someone else's personal data anyway, stop there, don't
  keep or pass on what you saw, and tell us exactly what it was. A personal
  data breach may have to be reported to the data protection authority within
  72 hours, so the sooner we hear, the better.
- No denial-of-service, no spam, and no social engineering of farms, their
  staff or their members.

We won't take legal action against research that keeps to these rules, and we
won't ask anyone else to.

## Scope

In scope is everything in this repository: the Django backend, the React
frontend, the nginx gateway configuration, the Docker setup, and the deploy and
backup scripts. We're most interested in:

- one farm reading or changing another farm's data;
- a member reaching another member's data, or any login reaching what its role
  shouldn't;
- login, two-factor authentication, step-up and session handling;
- the payment path: IBANs, SEPA mandates and direct-debit exports;
- a finalized invoice changing despite its protection.

Out of scope:

- a vulnerability in a dependency that doesn't affect Jasmin — report it
  upstream. If it does affect Jasmin, a heads-up is welcome;
- scanner output without a demonstrated impact, such as missing hardening
  headers. The Content Security Policy runs in report-only mode for now, which
  is known;
- attacks that need control of the victim's device or browser to begin with.

Questions about hardening your own installation, with no vulnerability behind
them, can go in a normal issue.
