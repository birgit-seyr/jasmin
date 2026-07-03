---
name: editable-table-reactive-disabled
description: How EditableTable evaluates a column's `disabled` — a FUNCTION `disabled` is re-run LIVE against the in-edit form values (buildLiveRecord → reactiveDisabled), so a cell can enable/disable in reaction to a SIBLING cell changing mid-edit (e.g. a seller cell that unlocks once a purchased share_article is picked). Use when a column must be conditionally editable based on another field, or when debugging "the cell won't re-enable when I change the other field in the same edit."
---

# EditableTable reactive `disabled`

## What works out of the box

`column.disabled` may be a **boolean** (static) or a **function** `(record) => boolean`.
A function is re-evaluated LIVE while a row/modal is being edited, against a record
that merges the current in-edit form values over the saved row:

- Inline editing: `EditableCell` builds `liveRecord = buildLiveRecord(record, Form.useWatch([], form), columns)` and computes `reactiveDisabled = column.disabled(liveRecord)`.
- Modal editing: `EditableModal.renderFormInput` does the same with its own form's watched values.

`buildLiveRecord` reverse-maps foreign-key columns: for a FK column it sets
`merged[foreignKey.valueField] = formValues[dataIndex]`. So a `disabled` predicate should read the **valueField** (the id), e.g. `record.share_article`, not the display `share_article_name`. Because both editors share ONE `<Form>` per editing row (`EditableTable` wraps the body in `<Form form={form} component={false}>`), changing one cell updates `formValues`, which re-runs every cell's `disabled`.

Canonical use — a column editable only when the row's selected article is purchased:

```tsx
const purchasedIds = useMemo(
  () => new Set(shareArticles.filter(a => a.is_purchased).map(a => String(a.value))),
  [shareArticles],
);
const overrides = useMemo(
  () => ({ disabled: (r: TableRecord) => !purchasedIds.has(String(r.share_article)) }),
  [purchasedIds],
);
const sellerColumn = useSellerColumn({ overrides });
```

Memoize the overrides object so the column identity is stable (the data hooks return a fresh array each render).

## The trap

`EditableTable.onCell` used to bake the **static** result of a function `disabled`
into the cell's `disabled` prop: `column.disabled(record)` against the *saved* record.
`EditableCell` then does `effectiveDisabled = disabled || reactiveDisabled`. So a
static `true` (article not purchased yet, or a brand-new `key === -1` row) **OR-shadows**
the live `reactiveDisabled` and the cell can NEVER re-enable mid-edit — even though the
live predicate correctly flips to `false`. Symptom: "it's editable for rows already
saved as purchased, but selecting a purchased article in edit mode doesn't unlock it."
(Modal editing didn't show the bug because `renderFormInput` recomputes from the live
record and ignores the static prop — so a page that only reproduced it was in *inline*
mode, driven by `ModalContext`'s `isModalMode`.)

The fix (in `EditableTable.onCell`): a function `disabled` must NOT be pre-evaluated —
leave it to `EditableCell`'s `reactiveDisabled`. Only a boolean is static:

```ts
const isDisabled =
  typeof column.disabled === "function" ? false : column.disabled;
// ... disabled: isDisabled || permissions.canEdit === false,
```

This is safe for existing function-disabled columns whose predicate reads only stable
fields (e.g. `record => record.key !== -1`): `liveRecord` carries the same `key`, so
`reactiveDisabled` returns the identical value. Display-mode behaviour is unchanged too
— with no active edit `formValues` is undefined, so `liveRecord === record` and the
click-to-edit gating stays as before.

## Files

- `src/shared/tables/BasicEditableTable/EditableTable.tsx` — `onCell` (don't bake static function-disabled); one shared `<Form>` per body.
- `src/shared/tables/BasicEditableTable/EditableCell.tsx` — `reactiveDisabled` + `effectiveDisabled = disabled || reactiveDisabled`; disabled cell renders a locked display and switches to an input when it re-enables.
- `src/shared/tables/BasicEditableTable/EditableModal.tsx` — `renderFormInput` recomputes `disabled` from `buildLiveRecord` (already live).
- `src/shared/tables/BasicEditableTable/buildLiveRecord.ts` — merges form values, reverse-maps FK `valueField`.
