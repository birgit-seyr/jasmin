---
name: bulk-partial-success-savepoints
description: How Jasmin bulk endpoints deliver partial success (HTTP 207) safely — wrap each item's DB work in a per-item savepoint so one IntegrityError/ProtectedError doesn't abort the whole batch. Use when writing or reviewing any bulk create / finalize / delete / set-paid / stock-inventory endpoint that loops over items collecting per-item errors under an outer @transaction.atomic.
---

# Bulk-endpoint partial success: per-item savepoints

## The trap

A bulk endpoint that wants partial success looks like this:

```python
@transaction.atomic                      # outer transaction
def post(self, request):
    results, errors = [], []
    for item in items:
        try:
            item.do_db_write()           # <-- NO savepoint
            results.append(...)
        except DatabaseError as exc:     # catches it, keeps looping
            errors.append({"id": item.id, "error": str(exc)})
    return Response({...207...})
```

This **looks** like it collects per-item errors and returns 207. It does not.
The moment ONE item raises a real `IntegrityError` / `DataError` /
`ProtectedError` (NOT NULL, unique, a PROTECT FK, a row deleted concurrently
under `select_for_update`), **PostgreSQL marks the entire transaction
aborted**. The `except DatabaseError` swallows that first error, but then:

- every subsequent query in the loop raises `TransactionManagementError`
  (which is also a `DatabaseError`, so it's also swallowed → silent), and
- the outer `@transaction.atomic` forces a rollback + re-raise on exit,
  **discarding every successful item and returning HTTP 500** instead of 207.

So the documented partial-success contract is violated exactly when it
matters most.

## The fix

Wrap **each item's DB work** in its own nested `with transaction.atomic():`
(a SAVEPOINT). A failing item then rolls back only itself and the connection
stays usable for the rest of the batch:

```python
for item in items:
    try:
        with transaction.atomic():       # per-item SAVEPOINT
            item.do_db_write()
        results.append(...)              # only on success
    except DatabaseError as exc:
        errors.append({"id": item.id, "error": str(exc)})
```

Rules that keep this correct:

- Let the exception propagate OUT of the `with` block (the `except` is
  OUTSIDE the `with`). Never catch-and-continue inside the savepoint.
- Append the success row only AFTER the last write, so a rolled-back
  savepoint never leaves a phantom success in `results`.
- Soft business-rule rejections (e.g. "already finalized", "has an invoice")
  should `append` to `errors` and `return`/`continue` BEFORE any write — they
  don't need the savepoint and won't double-report.

## Where this lives in the codebase

- **Reseller documents** (create / finalize / delete / set-paid):
  `apps/commissioning/views/reseller_views.py` → the shared
  `_run_per_order_bulk(orders, handler)` helper owns the loop + the savepoint +
  the per-item except trailer. All four bulk-document views route through it,
  so the savepoint is defined ONCE there. (Findings COR-18, COR-20.)
- **Stock inventory** (bulk_finalize / set_as_expected / set_to_zero):
  `apps/commissioning/views/stock_views.py` → savepoint inside the inner loop
  of `_process_grouped_stock_with_theoretical` (around the `process_item`
  call) and in the `bulk_set_to_zero_current_stock` loop body. (Finding
  COR-19.)

## How to test it (non-vacuously)

A mock that just `raise`s does NOT exercise the bug — the savepoint only
matters for a REAL DB error that aborts the transaction. Trigger an actual
`IntegrityError` and assert the connection survives:

```python
def test_db_error_in_one_item_does_not_abort_batch(self, tenant):
    from django.db import transaction
    good, bad = OrderFactory(), OrderFactory()

    def handler(order, results, errors):
        if order.pk == bad.pk:
            # duplicate of bad's unique (reseller, year, week, day) slot
            Order.objects.create(reseller=order.reseller, year=order.year,
                                 delivery_week=order.delivery_week,
                                 day_number=order.day_number)
        results.append({"order_id": str(order.id), "success": True})

    with transaction.atomic():                       # mimic the view's atomic
        results, errors = _run_per_order_bulk(
            Order.objects.filter(pk__in=[good.pk, bad.pk]), handler)
        assert Order.objects.filter(pk=good.pk).exists()   # connection usable
    assert str(good.id) in {r["order_id"] for r in results}      # good committed
    assert any(e["order_id"] == str(bad.id) for e in errors)     # bad reported
```

(See `apps/commissioning/tests/tests_views/test_reseller_views.py
::TestRunPerOrderBulkSavepoint`.)
