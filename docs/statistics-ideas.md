# Statistics & analytics — idea catalogue

A working backlog for the **Statistics** page (`/members/statistics`). Each row says
what the metric tells you, the chart form to use, where the data comes from, and a
rough effort. Pick from here; we build incrementally.

> **Why so much is feasible:** the core models are *time-bound*
> (`Subscription.valid_from/valid_until/cancelled_at`, `JasminUser.account_status` +
> status-transition timestamps + `date_joined`, `ShareTypeVariation` validity windows).
> That means "how many X were active **as of** month M" is a plain query at each period
> boundary — we get real time-series **without** adding an event-log. Skip the ones that
> genuinely need new tracking (marked 🔴).

**Effort legend** — 🟢 existing data, simple aggregate · 🟡 needs joins/grouping or a new
endpoint · 🔴 needs historical snapshots or tracking we don't have yet.

**Chart form** follows the `dataviz` method (magnitude → bars, change-over-time → line/area,
share-of-whole → donut *sparingly*, single headline → stat tile, matrix → heatmap).

---

## 1. Membership & growth

| Metric | What it tells you | Chart | Data source | Effort |
|---|---|---|---|---|
| **Active members over time** | Growth trajectory, the headline curve | Area (Zeitverlauf) | `JasminUser.account_status` + status timestamps; count active as-of each month | 🟡 |
| **New members / month** | Acquisition pace, seasonality | Bar | `date_joined` bucketed by month | 🟢 |
| **Cancellations / month + churn rate** | Are we leaking members? | Line (rate) + bar (count) | status transition → cancelled/inactive timestamp | 🟡 |
| **Cohort retention** | % of each join-cohort still active after N months | Heatmap (cohort × months) | `date_joined` + status timestamps | 🔴 |
| **Member status breakdown** | active / paused / trial / cancelled mix right now | Donut or stacked bar | `account_status` | 🟢 |
| **Avg member tenure** | Loyalty in one number | Stat tile | join → churn span | 🟡 |

## 2. Subscriptions & shares (Abos)

| Metric | What it tells you | Chart | Data source | Effort |
|---|---|---|---|---|
| **Active subscriptions over time** | Demand trajectory | Area | `Subscription` valid window + `admin_confirmed`, `cancelled_at` | 🟡 |
| **Subscriptions by share type & size (S/M/L)** | Product mix — *(the bar you already have)* | Grouped/stacked bar | `Subscription` × `ShareTypeVariation.size` / `share_type` | 🟢 |
| **Size-mix shift across seasons** | Are members up/down-sizing on renewal? | 100% stacked area | size distribution per season | 🟡 |
| **Virtual vs physical variation uptake** | How popular are bundle shares? | Bar | `ShareTypeVariation.variation_type` | 🟢 |
| **Avg shares per member** | Multi-share households | Stat tile + histogram | subscriptions grouped by member | 🟢 |
| **Renewal rate at season end** | Stickiness at the key decision point | Stat tile / line | subscriptions expiring vs renewed | 🟡 |
| **Waiting-list size over time & by station** | Unmet demand — where to add capacity | Line + bar | `Subscription.on_waiting_list` | 🟡 |
| **Trial → paid conversion** | Is the trial working? | Funnel / stat tile | `is_trial` subs → later non-trial / active | 🟡 |

## 3. Solidarity pricing 🌱 (your differentiator)

The Solawi principle is that members pay **what they can** around a reference price. These
metrics show whether the community actually balances — nobody else's dashboard has them.

| Metric | What it tells you | Chart | Data source | Effort |
|---|---|---|---|---|
| **Chosen price vs reference — distribution** | How far above/below reference members pay | Histogram / diverging bar | `Subscription.price_per_delivery` vs variation reference `price_per_delivery` | 🟡 |
| **% paying above / at / below reference** | Solidarity participation | Donut (3 slices) | same | 🟡 |
| **Solidarity balance** | Σ(above reference) vs Σ(below) — *does it net out?* | Two stat tiles + bar | same | 🟡 |
| **Avg solidarity uplift per share** | The community's generosity in one number | Stat tile | same | 🟢 |
| **Solidarity by station / share type** | Where support concentrates | Bar | same, grouped | 🟡 |

## 4. Deliveries & logistics (Commissioning)

| Metric | What it tells you | Chart | Data source | Effort |
|---|---|---|---|---|
| **Deliveries / week** | Operational volume, seasonality | Line | `ShareDelivery` counts by ISO week | 🟢 |
| **Load per delivery station / station-day** | Where the boxes go | Bar + map | deliveries grouped by `delivery_station_day` | 🟢 |
| **Station-day capacity utilization** | Free vs total slots — pressure map | Heatmap (station × week) | `DeliveryStationDay.capacity` vs demand | 🟡 |
| **Physical units to pack / week by size** | Production/packing plan | Stacked bar | `batch_get_physical_variation_totals_for_weeks` (already exists) | 🟢 |
| **Joker usage / week + per-member spread** | Skipped deliveries → production adjustment | Line + histogram | `ShareDelivery.joker_taken` | 🟢 |
| **Opt-in rate for on-off shares** | Uptake of optional/one-off boxes | Bar/line | `ShareDelivery.is_opted_in` where `requires_optin` | 🟡 |
| **Bulk vs boxes split (MIXED mode)** | Packing-line balance | Donut | `ShareTypeVariation.is_packed_bulk` | 🟢 |
| **Demand: subscription-derived vs external CSV** | Forecast source agreement | Line comparison | `ShareDemandService` (both backends) | 🟡 |
| **Tours / day & units per tour** | Route load | Bar | `DeliveryStationDay.tour_number` | 🟡 |

## 5. Financial & economics

| Metric | What it tells you | Chart | Data source | Effort |
|---|---|---|---|---|
| **Recurring revenue over time** | The money curve (price/delivery × active subs × frequency) | Area | `Subscription.price_per_delivery` + `payment_cycle` over time | 🟡 |
| **Revenue by share type / size** | What earns | Bar | subs × variation | 🟢 |
| **Avg revenue per member / per share** | Unit economics | Stat tiles | same | 🟢 |
| **Payment-cycle mix** | monthly / quarterly / yearly split | Donut | `Subscription.payment_cycle` | 🟢 |
| **Outstanding / overdue & collection rate** | Cash health | Line + stat tile | `apps/payments` charges/debits | 🟡 |
| **SEPA mandate coverage** | % of members with an active mandate | Gauge / stat tile | `BillingProfile.sepa_mandate_signed_at` | 🟢 |
| **Station fees owed** | What we owe pickup hosts | Bar | `DeliveryStation.fee_per_box/month/year_net` | 🟢 |

## 6. Geography & stations

| Metric | What it tells you | Chart | Data source | Effort |
|---|---|---|---|---|
| **Members per station** | Catchment | Map (react-leaflet) + bar | subs → `default_delivery_station_day.delivery_station` | 🟢 |
| **Capacity pressure by station** | Over/under-subscribed pickup points | Diverging bar | subscribed vs `capacity` | 🟡 |
| **Station growth/decline** | Which stations trend up/down | Small-multiples line | subs per station over time | 🔴 |

## 7. Engagement & compliance (nice-to-have)

| Metric | What it tells you | Chart | Data source | Effort |
|---|---|---|---|---|
| **Consent / GDPR status coverage** | Compliance posture | Donut / stat tile | `apps/gdpr`, consents | 🟢 |
| **Opt-in deadline compliance** | Last-minute change load | Line | opt-in timestamps vs deadline | 🟡 |
| **Portal logins / email engagement** | Member activity | Line | needs event/audit tracking | 🔴 |

---

## Suggested first sprint (all 🟢, mostly existing data)

A tight, high-signal starter set — each is one card, one query:

1. **Member status breakdown** (donut) + **new members / month** (bar) — §1
2. **Subscriptions by share type & size** (bar) — §2 *(already scaffolded)*
3. **Payment-cycle mix** (donut) — §5
4. **Deliveries / week** (line) + **joker usage / week** (line) — §4
5. **Physical units to pack / week by size** (stacked bar) — §4 *(reuses `batch_get_physical_variation_totals_for_weeks`)*
6. **One Solawi differentiator:** **chosen price vs reference** distribution — §3

## How we'd build them

- **Backend:** one read-only, per-tenant `statistics` viewset with focused aggregate
  endpoints (`GET .../statistics/members-by-status`, `.../deliveries-by-week?year=…`, …).
  Validate query params via the central `PARAM_CATALOGUE` (see the
  `query-params-catalogue-validation` skill). Time-series endpoints take a
  `date_from`/`date_to` (or year/week) range and return `[{ bucket, value }]`.
- **Frontend:** each metric is a `Card` on the Statistics page with a Recharts chart,
  theme-tokened colors, and — for time-series — the shared `useDateRangePresets()` +
  `RangePicker` window (as the scaffold already does). Fetch via generated Orval hooks.
- **Design:** follow the `dataviz` method — fixed categorical order, one axis, legend only
  for ≥2 series, hover tooltips, validated palette.

_Data-source field names are from the current models; confirm exact names when wiring each
endpoint._
