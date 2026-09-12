# Domain glossary

The vocabulary the codebase uses, and the traps in it. Read this before your
first change to `apps/commissioning/` — most of the confusion new contributors
hit is naming, not logic.

## The `Share*` family

This is the #1 source of naming confusion. Two axes cause it:

1. **`Share` and `CoopShare` are unrelated models.** `Share` is a weekly produce
   delivery; `CoopShare` is a legal capital share (Geschäftsanteil). Never
   conflate them — function names use `share` vs `coop_share` deliberately.
2. **Type → Variation → Share → Content is a containment chain**, each level a
   narrower scope.

Everything below lives in `apps/commissioning/models/`.

| Term | Defined in | One-liner |
|------|-----------|-----------|
| **ShareOption** | `shares.py` (enum) | Hardcoded produce categories (`HARVEST_SHARE`, `OIL_SHARE`, …). Extended only from code, never per-tenant. |
| **ShareType** | `shares.py` (TimeBound) | A time-bound *kind* of share offering, e.g. harvest share, honey share. One open per `ShareOption`. |
| **ShareTypeVariation** | `shares.py` (TimeBound) | A *size* child of a ShareType, e.g. "harvest share S". This is what a member actually subscribes to and what gets priced. |
| **Subscription** | `members.py` (TimeBound) | A member's time-bound agreement to receive one ShareTypeVariation (`valid_from → valid_until`; trial / term / renewal chain). Links Member ↔ Variation. |
| **Share** | `shares.py` | One **weekly delivery instance**: a `(year, delivery_week, delivery_day, share_type_variation)` row. Purely operational; no member link. |
| **ShareContent** | `shares.py` | The produce line(s) for one Share **at one delivery station** — "2 kg spinach S at Station A, W23". Finalizable + archivable. |
| **ShareDelivery** | `shares.py` | Per-member confirm/skip record for a Share: joker (skip), donation-joker, opt-in state. Links Subscription ↔ Share. |
| **CoopShare** | `members.py` | **Legal/financial, NOT produce.** A cooperative equity share (Geschäftsanteil, GenG) — `amount_of_coop_shares` × `value_one_coop_share`, with statutory retention + payback on exit. Belongs to a Member. |

## Hierarchy (policy → execution)

```
ShareOption (enum)
└─ ShareType                "harvest share, valid 2024"
   └─ ShareTypeVariation    "harvest share S, valid 2024"   ← members subscribe to THIS
      ├─ Subscription       "Alice: harvest-S, 2024"
      │  └─ ShareDelivery   "Alice, W23: deliver? joker? opted-in?"
      └─ Share              "W23/2024, harvest-S, Saturday"  ← one row per week
         └─ ShareContent    "W23 harvest-S @ Station A: 2kg spinach S"
```

## Share vs CoopShare — the critical one

`Share` / `ShareContent` / `ShareDelivery` answer *"what produce is delivered
this week, and to whom?"* — ephemeral, weekly, archived as the season passes.

`CoopShare` answers *"how much of the co-op does this member own, and when is it
refundable?"* — persistent capital that a member must hold a minimum of to be
active, divested only on cancellation + payback.

They share a prefix and nothing else.

## Other conventions worth knowing

- **`valid_from` dates are always Mondays.** Time-bound models (`TimeBound`) are
  aligned to ISO weeks throughout.
- **Model IDs are strings, not UUIDs or ints.** `TapirModel.id` is a `CharField`,
  which means `qs.filter(pk=some_instance)` silently matches nothing — always
  pass `.pk` explicitly. See the CharField pitfall section in
  [`CLAUDE.md`](../CLAUDE.md).
- **Money and stock quantities are `Decimal` end-to-end** and cross the API as
  strings, never floats.
