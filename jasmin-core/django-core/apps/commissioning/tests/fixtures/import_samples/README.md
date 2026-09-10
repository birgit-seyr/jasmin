# Data-list import — sample CSVs

Filled-in samples for the office CSV upload (Members page → import modal, and
Abos page → "import existing subscriptions" modal). They double as the input for
the HTTP upload test in
`apps/commissioning/tests/tests_views/test_data_import_view.py`, so keep the two
in sync if you edit either.

Both files use the **3-row template layout** the download button produces:

1. row 0 — human-readable column titles (ignored on import)
2. row 1 — `dataIndex` field names (the actual upload schema)
3. row 2 — type hints (ignored on import)

then one data row per record.

## `members_sample.csv`

Creates **unconfirmed** members (the office confirms them afterwards). Only
writable `Member` fields are set.

`member_number` is writable **on the import path only** (the office grid keeps
the column read-only). A tenant migrating off another system carries its
existing Mitgliedsnummern over, and every other sample below resolves its member
by that number — so import the members first, then the rest. Rules:

- Blank is fine: the member gets no number until the office confirms them, at
  which point `Member._post_confirm` assigns `Max(member_number) + 1` — above
  the imported block, so the two numbering sources never collide.
- The number is unique; a collision (with an existing member or an earlier row
  of the same file) is a per-row error, not a partial import.
- A **trial** row must leave it blank — trial members are not Mitglieder under
  GenG and hold no Mitgliedsnummer (`member.number_not_allowed_for_trial`).

`entry_date` is likewise writable here for the manual-transfer case (migrating
members with a historical admission date); it is otherwise server-stamped.
`email` is unique, so re-uploading the same file reports per-row conflicts on the
second run.

## `subscriptions_sample.csv`

Creates **unconfirmed draft** subscriptions — no deliveries, charges, or capacity
reservation happen until the office confirms each one through the normal flow.
Every foreign key is referenced by a human-readable **natural key**, not a DB id,
so the values below must already exist in the tenant:

| column             | resolves against                                     |
| ------------------ | ---------------------------------------------------- |
| `member_number`    | `Member.member_number` (unique)                      |
| `share_type`+`size`| the `ShareTypeVariation` active at `valid_from`      |
| `payment_cycle`    | `PaymentCycle.choice` (e.g. `MONTHLY`)               |
| `delivery_station` + `delivery_day` | the active `DeliveryStationDay` (station `short_name` + day number, `0`=Mon) — provide BOTH or neither |

Rules the importer enforces per row:

- `valid_from` must be a **Monday**, `valid_until` a **Sunday**.
- `valid_until` is **required** — open-ended subscriptions are not allowed.
- `price_per_delivery` is optional (blank → the variation's default price).

To try these by hand, adjust the natural-key values to match your tenant's real
share types / stations / member numbers first.

## `sepa_mandates_sample.csv`

Imports **SEPA direct-debit mandates**. A mandate is not its own model — it is
the SEPA fields on a member's `payments.BillingProfile` (one per member), so each
row **creates that member's billing profile**, keyed by `member_number`.

**Create-only**: a member who already has a billing profile is reported as a
per-row conflict and left untouched (a live mandate must never be silently
overwritten). `sepa_mandate_reference` is kept when the CSV provides one
(continuity with the member's existing mandate at the bank) and auto-generated
when blank. `iban` is validated, and `account_holder` + `sepa_mandate_signed_at`
are required (an active SEPA mandate needs them).

| column                           | notes                                     |
| -------------------------------- | ----------------------------------------- |
| `member_number`                  | `Member.member_number` (unique)           |
| `account_holder`                 | required — name on the bank account       |
| `iban`                           | required — validated                      |
| `sepa_mandate_reference`         | optional — blank auto-generates a new one |
| `sepa_mandate_signed_at`         | required — signed date                    |
| `sepa_mandate_paper_received_at` | optional — paper mandate received date    |

## `coop_shares_sample.csv` — Members page → "import cooperative shares"

Creates members' **cooperative shares** (`CoopShare`, GenG equity) keyed by
`member_number`, unconfirmed. `save()` → `full_clean()` enforces the min/max
equity window per row for confirmed members (skipped for unconfirmed / trial
applicants).

| column                  | notes                                             |
| ----------------------- | ------------------------------------------------- |
| `member_number`         | `Member.member_number` (unique)                   |
| `amount_of_coop_shares` | required — number of shares held                  |
| `value_one_coop_share`  | required — value of a single share                |
| `is_increase`           | optional — increase over the mandatory amount     |
| `note`                  | optional — free text                              |
