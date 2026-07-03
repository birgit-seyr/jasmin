---
name: query-params-catalogue-validation
description: How Jasmin DRF endpoints validate query parameters — route every read through validate_query_params(request, required=[...], optional=[...]) against the central PARAM_CATALOGUE instead of request.query_params.get() + manual int()/strptime() (which raises a bare ValueError → HTTP 500). Use when writing or reviewing any commissioning viewset/view that reads year/week/day_number/date/bool/choice query params (list, get_queryset, destroy, exports, statistics).
---

# Query-param validation via the central catalogue

## The trap

An endpoint reads query params straight off the request and forwards them:

```python
def destroy(self, request, pk=None):
    year = request.query_params.get("year")           # str | None
    delivery_week = request.query_params.get("delivery_week")
    ...
    Service.delete(year=year, delivery_week=delivery_week, ...)  # int ORM lookups
```

`?year=abc` (or a missing param) reaches an integer column lookup
(`order__year=...`) and Django's `IntegerField.get_prep_value` raises a **bare
`ValueError`** — NOT a `django.core.exceptions.ValidationError`. The DRF
exception handler (`core/exception_handler.py`) doesn't recognise it, so it
falls through to the generic branch and returns **HTTP 500
("An unexpected error occurred.")** instead of a 400. Same trap with manual
`int(raw)` / `datetime.strptime(raw, ...)` at the call site. The
`@extend_schema(parameters=[get_year_parameter(required=True), ...])` then
_promises_ validation that never runs.

## The fix

Route the read through the central catalogue. It's the front door for every
query param.

```python
from ..utils.query_params import validate_query_params  # already imported in most viewsets

def destroy(self, request, pk=None):
    params = validate_query_params(
        request,
        required=["year", "delivery_week", "day_number", "reseller", "order_id"],
        # optional=[...] for non-required params; absent ones return their
        # catalogue default (usually None)
    )
    year = params["year"]                 # already an int, range-checked
    reseller = params["reseller"]         # str passthrough
    ...
```

Now `?year=abc` → `InvalidQueryParam` (HTTP **400**, code `query.invalid_param`,
`field="year"`); a required-but-missing param → 400 too; and the runtime matches
the `required`-int `@extend_schema` contract.

## What the catalogue gives you (`apps/commissioning/utils/query_params.py`)

- **`PARAM_CATALOGUE`** declares each param ONCE as a `ParamSpec(kind, ...)`.
  Coercion by kind:
  - `int` — parsed + range-checked (kills the `int('abc')` / `int(None)` 500s).
  - `date` — validated `YYYY-MM-DD` and **returned as a `date` object** (not a
    string) — which is what queryset/manager methods like
    `active_at_date(target_date: date)` / `active_at_date_or_future(...)` expect.
  - `bool` — strict `true`/`false` (a typo'd `?flag=ture` 400s, never silently `False`).
  - `choice` — checked against an allowed set.
  - `str` — passthrough (FK ids are STR; a bad value yields an empty filter, not a 500).
- **`validate_week_scope(request)`** — convenience wrapper returning the recurring
  `(year, delivery_week, day_number, is_past)` bundle. Use it for the common
  week-scoped list endpoint instead of re-listing those four names.
- Raised error: **`InvalidQueryParam`** (`core.errors`, code `query.invalid_param`,
  → 400 with `field`). Don't hand-build a `Response(status=400)`.

## Rules / gotchas

- **Never read a typed query param raw.** No `request.query_params.get("year")`
  followed by `int()`/`strptime()`/passing into an int/date ORM lookup. If you
  see that in a diff, it's this bug.
- **Add new params to `PARAM_CATALOGUE`, don't read them raw.** Naming a param
  that isn't catalogued raises `KeyError` (programmer error, by design). A stale
  `# NOT in PARAM_CATALOGUE` comment is a smell — the spec is usually already there.
- **`validate_query_params` only inspects `request.query_params`**, never the
  body. For POST/PATCH-body int parsing use
  `validate_and_parse_int_params(..., source="data")` in
  `apps/commissioning/utils/validation_utils.py`. A DELETE/endpoint that read
  query-OR-body can drop the body source (backward-compat is not required) and
  go query-only to match its siblings.
- **Keep `@extend_schema` honest.** If you validate a param as `required`, the
  schema's `get_*_parameter(required=True)` should agree (and vice-versa).
- This is an established standard, not a new idea: ~19 commissioning
  viewset/view modules already use it. Canonical examples:
  `CrateOrderContentViewSet.list`/`destroy` (resellers_viewsets.py),
  `SharesDeliveryDayViewSet.get_queryset` (choices_models_viewsets.py).
