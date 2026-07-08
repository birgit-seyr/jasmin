import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { ExplainerText, HideInactiveSwitch } from "@shared/ui";

import EditableTable from "./BasicEditableTable";
import type {
  EditableColumnConfig,
  EditableTableProps,
  TableRecord,
} from "./BasicEditableTable/types";
import {
  useCrudListPage,
  type CrudListPageApi,
  type UseCrudListPageOptions,
} from "./useCrudListPage";

/** A slot that's either static content or a render-prop receiving the list
 *  state (so CSV buttons / modals can reach `invalidate`, `data`, …). */
type CrudSlot<TRow extends TableRecord> =
  | ReactNode
  | ((list: CrudListPageApi<TRow>) => ReactNode);

export interface CrudListPageProps<
  TRow extends TableRecord,
> extends UseCrudListPageOptions<TRow> {
  /** i18n key for the `<h1>` title. */
  titleKey: string;
  /** i18n key for the `<h5>` subtitle (optional). */
  descriptionKey?: string;
  /** i18n key for the trailing `ExplainerText` (optional). */
  explainerKey?: string;
  columns: EditableColumnConfig<TRow>[];
  uniqueCheck?: string | string[] | null;
  uniqueCheckMessage?: string | null;
  focusIndex?: string;
  className?: string;
  customSave?: EditableTableProps<TRow>["customSave"];
  showSearchBar?: boolean;
  pagination?: boolean;
  deleteContext?: Record<string, unknown> | string | null;
  /** Extra actions shown next to the title. Static node or a render-prop
   *  receiving the list state (for a CSV export needing `data`/`columns`). */
  headerActions?: CrudSlot<TRow>;
  /** Trailing content after the table (modals, CSV template/upload). Static
   *  node or a render-prop receiving the list state (for `invalidate`, …). */
  children?: CrudSlot<TRow>;
}

/** Resolve a slot that may be a render-prop against the list state. */
function renderSlot<TRow extends TableRecord>(
  slot: CrudSlot<TRow> | undefined,
  list: CrudListPageApi<TRow>,
): ReactNode {
  return typeof slot === "function" ? slot(list) : slot;
}

/**
 * The pure-skeleton commissioning `List*` page as a component: title +
 * (optional) description + hide-inactive switch + `EditableTable` + explainer.
 * Owns all the CRUD boilerplate via {@link useCrudListPage}; the caller supplies
 * only the resource, columns, and i18n keys. Header actions and trailing modals
 * slot in via `headerActions` / `children`, so mid-complexity pages can use it
 * too; genuinely complex pages call `useCrudListPage` directly instead.
 */
export function CrudListPage<TRow extends TableRecord>({
  titleKey,
  descriptionKey,
  explainerKey,
  columns,
  uniqueCheck,
  uniqueCheckMessage,
  focusIndex,
  className,
  customSave,
  showSearchBar,
  pagination,
  deleteContext,
  headerActions,
  children,
  ...crudOptions
}: CrudListPageProps<TRow>) {
  const { t } = useTranslation();
  const list = useCrudListPage<TRow>(crudOptions);
  const resolvedHeader = renderSlot(headerActions, list);
  const resolvedChildren = renderSlot(children, list);

  return (
    <div>
      {resolvedHeader ? (
        <div className="flex-between">
          <h1>{t(titleKey)}</h1>
          {resolvedHeader}
        </div>
      ) : (
        <h1>{t(titleKey)}</h1>
      )}
      {descriptionKey && <h5>{t(descriptionKey)}</h5>}

      {list.showHideInactive && (
        <HideInactiveSwitch
          value={list.hideInactive}
          onChange={list.setHideInactive}
        />
      )}

      <EditableTable
        columns={columns}
        apiFunctions={list.apiFunctions}
        initialData={list.filteredData}
        loading={list.isLoading}
        onSaveSuccess={list.onSaveSuccess}
        onDeleteSuccess={list.onDeleteSuccess}
        customEdit={list.customEdit}
        customSave={customSave}
        permissions={list.permissions}
        uniqueCheck={uniqueCheck}
        uniqueCheckMessage={uniqueCheckMessage}
        focusIndex={focusIndex}
        showSearchBar={showSearchBar}
        pagination={pagination}
        deleteContext={deleteContext}
        className={className}
      />

      {explainerKey && (
        <ExplainerText title={t("common.info")}>
          {t(explainerKey)}
        </ExplainerText>
      )}

      {/* Trailing slot AFTER the explainer — matches where pages put CSV
          upload buttons / modals (a CSV button below the info text). */}
      {resolvedChildren}
    </div>
  );
}
