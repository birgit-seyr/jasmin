---
name: reuse-frontend-building-blocks
description: The catalogue of existing Jasmin react-core components/hooks/utils to REUSE instead of hand-rolling — tables (EditableTable), column hooks, date-range picker + presets, date formatting, CSV export, currency, selectors, entity data hooks. Use when building or reviewing any new page/table/report/download/form so you wire the shared pieces instead of reinventing a plain AntD Table, an inline date range, a bespoke CSV writer, or a hardcoded date format.
---

# Reuse existing building blocks (don't hand-roll)

CLAUDE.md standing rule: **always prefer an existing component/hook/util over
hand-rolling.** A plain AntD `Table`, an inline `RangePicker`, a custom CSV
writer, or `dayjs().format("YYYY-MM-DD")` when a shared equivalent exists is a
defect. This is the catalogue; reference page: `src/features/commissioning/pages/DeliveryStationFees.tsx`.

## Tables

- **`EditableTable`** (`@shared/tables`) for every tabular view — editable AND
  read-only. Read-only report: pass `permissions={READ_ONLY_PERMISSION}` and
  `initialData` (no `apiFunctions`). Columns are `EditableColumnConfig<TableRecord>[]`
  with `render`. Rows need a `key` (and usually `id`).
- **Data ownership (CLAUDE.md):** either the table owns data (`apiFunctions.list`
  - `showSearchBar`, no `initialData`) OR the page owns it (a `use*List` query →
    `initialData`, no `list`). Never both (double fetch).
- **`loading` prop:** `isFetching` for filter-driven tables (year/week/range),
  `isLoading` for plain lists, `isPending` for mutations.
- Per-row edit/delete gating: `permissions.canEditRecord` / `canDeleteRecord`
  (`(record) => boolean`); `isUnprotectedRow` is the shared delete guard.

## Column definitions — `use*Column(s)` hooks

Don't inline column objects that already have a hook. Shared:
`useTimeBoundColumns` (valid_from Monday-only / valid_until Sunday-only
datepickers), `useActiveStatusColumn` (active/upcoming/expired from
valid_from/valid_until). Commissioning: `useSellerColumn`, `useShareArticleColumn`,
`useNoteColumn`, `useAmountUnitSizeColumns`, `useIsActiveColumn`, … (barrel:
`@features/commissioning/hooks`). Function `disabled: (record) => …` is evaluated
LIVE against in-edit form values (see the `editable-table-reactive-disabled` skill).

## Dates

- **Range picker:** AntD `RangePicker` + **`useDateRangePresets()`** (`@hooks/index`)
  for the quick-range presets — same UX as the CSV export modals.
- **Formatting:** **`useDateFormat()`** (`@hooks/index`) — `dateFormat` (feed the
  picker `format=`), `formatDate(value)` (cells), **`formatDateForAPI(value)`**
  (`YYYY-MM-DD` for query params/payloads). NEVER hardcode `"YYYY-MM-DD"` for
  display or `dayjs().format(...)` inline.

## CSV export

- Client-side from loaded rows: **`buildCsvString(headers, rows, dialect?)`** +
  **`downloadCsvBlob(csvString, filename)`** (`@shared/utils`) — handles escaping,
  formula-injection safety, and the Excel BOM. Don't write your own `Blob`/anchor
  or cell-quoting.
- Date-range export fetched from the backend (honors the tenant `csv_format`):
  **`ExportCsvDateRangeModal`** (`@features/commissioning/modals/csv`) — pass a
  `fetchCsv({date_from, date_to, ...})` returning the CSV string.

## Money / selectors / data

- **Currency:** `useCurrency()` (`currencySymbol`, formatters).
- **Selectors:** `src/shared/selectors/*` (`YearSelector`, `WeekSelector`,
  `MonthSelector`, `DaySelector`, `MemberSelector`, `ResellerSelector`,
  `ShareTypeSelector`).
- **Data:** the Orval `use*List` hooks (`@shared/api/generated/**`) + the entity
  wrappers (`useDeliveryStations`, `useShareTypeVariations`, `useSellers`,
  `useShareArticles`, …). Almost never raw axios/url.

## Boundary gotcha

`src/shared/**` must NOT import `@features/*` (ESLint-enforced one-way layering).
So a shared component (e.g. a sidebar) that needs feature data must call the
**generated client** directly (`@shared/api/generated/**`, which is shared), not
the feature's `use<Entity>` wrapper. Example: `CommissioningSidebar` gates the
fee-billing entry via `useCommissioningDeliveryStationsList({}, { query: { enabled: isOffice } })`,
not the `useDeliveryStations` feature hook.

## If it doesn't exist

Build it in `src/shared/` (ui/hooks/tables/selectors) so the next page reuses it —
don't leave a one-off in a single page.
