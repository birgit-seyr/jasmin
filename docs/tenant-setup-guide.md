# Setting up a tenant's base data

What to fill in, and in what order, when configuring a tenant from scratch — a
fresh production tenant, or a local one after `make dev-reset`.

Each step builds on entities created in the ones before it, so working
top-to-bottom means you always have something to link to. Jumping ahead leaves
you with empty dropdowns.

Paths below are relative to the tenant's own host — locally that's
`http://test.localhost:3000`, in production the tenant's subdomain.

## 1. Share types and their sizes

**`/configuration/subscriptions`**

Define every share type the CSA offers (e.g. harvest share, bread share) along
with its size variations (e.g. S / M / L).

These are the products members subscribe to, and everything downstream —
forecasts, planning, packing, invoicing — is built on top of them, so they come
first.

## 2. Delivery days

**`/configuration/time-management`**

Set up the weekly days on which shares are handed out. They define the rhythm of
the season and are referenced by stations, tours, and the harvest/packing lists,
so they need to exist before any of those.

## 3. The master lists — produce and pickup points

- **Share articles** — the actual goods that make up a share (vegetables, bread,
  …): **`/commissioning/list-harvest-share-articles`**
- **Delivery stations** — the physical points where members collect their
  shares: **`/commissioning/list-delivery-stations`**

## 4. Assign delivery days to each station

**`/commissioning/list-delivery-stations`** → open a station's modal

A station only operates on certain delivery days; linking the two tells the
system which station is active on which day. This is what the harvest/packing
and station-overview screens scope by.

## 5. Assign the stations to tours

**`/commissioning/delivery-tours`**

Group the stations into the routes a driver actually takes. Tours drive the
per-tour breakdowns shown in the packing list and the station overview, so they
come last, once every station exists and has its delivery days.

---

Once these five are in place the operational screens (forecast, harvesting list,
packing list, station overview) have everything they need, and members can be
imported or invited.
