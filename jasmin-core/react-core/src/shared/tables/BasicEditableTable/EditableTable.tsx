import { EmptyHint } from "@/shared/ui";
import {
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
  SaveOutlined,
  SearchOutlined,
  UndoOutlined,
} from "@ant-design/icons";
import { useIsMobile, useNumberFormat } from "@hooks/index";
import { useModal } from "@shared/contexts/ModalContext";
import axiosService from "@shared/services/api";
import {
  calculateTableScrollWidth,
  createBooleanSorter,
  createDateSorter,
  createNumberSorter,
  createStringSorter,
} from "@shared/utils";
import {
  Alert,
  Button,
  Checkbox,
  Form,
  Input,
  Popconfirm,
  Space,
  Table,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import type {
  ChangeEvent,
  ComponentProps,
  CSSProperties,
  FC,
  Key,
  ReactElement,
  ReactNode,
} from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import EditableCell from "./EditableCell";
import EditableModal from "./EditableModal";
import MobileCardList from "./MobileCardList";
import TableSearchInput from "./TableSearchInput";
import {
  allowsRow,
  canDeleteRow,
  canEditRow,
  hasRowActions,
} from "./rowPermissions";
import type {
  EditableColumnConfig,
  EditableTableProps,
  InputType,
  SummaryRow,
  TableRecord,
} from "./types";
import { useAddShortcut } from "./useAddShortcut";
import { useEditableTable } from "./useEditableTable";
import { useInitialDataSync, useUpdatedRows } from "./useInitialDataSync";
import { useRowSelectionState } from "./useRowSelectionState";

// The default for `initialData`. The row-sync effect depends on it, so it has to
// be the same array on every render: a fresh `[]` would re-run the effect, whose
// new rows render the table again, without end.
const NO_ROWS: TableRecord[] = [];

// Table.Summary.Cell doesn't expose style prop in its types but it works at runtime
const StyledSummaryCell = Table.Summary.Cell as unknown as FC<
  ComponentProps<typeof Table.Summary.Cell> & { style?: CSSProperties }
>;

/**
 * Maps an `InputType` to a default sorter for the given dataIndex.
 * Returns `undefined` for input types that have no obvious sort order
 * (e.g. `optional` notes, free-form text fields are still string-sorted;
 * inputs with no inputType are skipped by the caller).
 */
const inferSorterForInputType = <T extends Record<string, unknown>>(
  inputType: InputType | undefined,
  dataIndex: string,
): ((a: T, b: T) => number) | undefined => {
  switch (inputType) {
    case "text":
    case "select":
    case "optional":
    case "time":
      return createStringSorter(dataIndex) as (a: T, b: T) => number;
    case "checkbox":
    case "switch":
      return createBooleanSorter(dataIndex) as (a: T, b: T) => number;
    case "date":
    case "datepicker":
      return createDateSorter(dataIndex) as (a: T, b: T) => number;
    case "number":
    case "integer":
    case "positive_integer":
    case "negative_integer":
    case "decimal1":
    case "decimal2":
    case "decimal3":
    case "positive_decimal2":
    case "negative_decimal2":
    case "positive_decimal3":
    case "negative_decimal3":
    case "percentage":
    case "kw":
      return createNumberSorter(dataIndex) as (a: T, b: T) => number;
    default:
      return undefined;
  }
};

// Pure column transforms — module-scope so they're stable references and can
// stay out of the enhancedColumns useMemo deps.
function getEnhancedColumnWidth<T extends TableRecord>(
  column: EditableColumnConfig<T>,
): string | undefined {
  if (column.width) return column.width as string;
  if (column.dataIndex && column.dataIndex.endsWith("unit")) return "8em";
  return undefined;
}

function enhanceCheckboxColumns<T extends TableRecord>(
  cols: EditableColumnConfig<T>[],
): EditableColumnConfig<T>[] {
  return cols.map((col) => {
    if (col.children && Array.isArray(col.children)) {
      return {
        ...col,
        children: enhanceCheckboxColumns(col.children),
      };
    }
    if (col.inputType === "checkbox") {
      return {
        ...col,
        width: col.width || (col.sorter ? "4em" : "2.5em"),
        align: col.align || "center",
        title: (col.title as ReactElement<{ className?: string }>)?.props
          ?.className ? (
          col.title
        ) : (
          <span className="checkbox-column-title">{col.title}</span>
        ),
        render:
          col.render ||
          ((_: unknown, record: T) => {
            if (record.key === "summary-row") return null;
            return (
              <Checkbox
                checked={Boolean(
                  (record as Record<string, unknown>)[col.dataIndex],
                )}
                disabled
                className="green-checkbox"
              />
            );
          }),
      };
    }
    if (col.dataIndex && col.dataIndex.endsWith("unit")) {
      return { ...col, width: getEnhancedColumnWidth(col) };
    }
    return col;
  });
}

function withAutoSorter<T extends TableRecord>(
  col: EditableColumnConfig<T>,
): EditableColumnConfig<T> {
  if (
    col.sorter !== undefined ||
    col.sortable !== true ||
    col.children ||
    !col.dataIndex
  ) {
    return col;
  }
  const sorter = inferSorterForInputType<T>(col.inputType, col.dataIndex);
  return sorter ? { ...col, sorter } : col;
}

const EditableTable = <T extends TableRecord = TableRecord>({
  columns,
  apiEndpoints = {},
  apiFunctions,
  baseParams = {},
  initialData = NO_ROWS as T[],
  // Destructured (not left to fall into `...tableProps`) so the caller's
  // data-fetch loading is OR-ed with the table's own save/delete loading
  // below, instead of silently overriding it via the prop spread.
  loading: loadingProp = false,
  onDataChange,
  permissions = {},
  showActions,
  size = "small",
  customSave = null,
  customEdit = null,
  customDelete = null,
  customUpdate = null,
  focusIndex,
  rowSelection = null,
  onSelectedRowsChange = null,
  selectedRowKeys,
  summaryRows = [],
  summaryLabelColumnIndex = 0,
  summaryPosition = "top",
  pagination = false,
  showSearchBar = false,
  deleteContext = null,
  forceInlineMode = false,
  uniqueCheck = null,
  uniqueCheckMessage = null,
  uniqueCheckRows,
  onSaveSuccess = null,
  onDeleteSuccess = null,
  renderMobileCard,
  keyboardAddShortcut = false,
  autoScrollX = true,
  pinNewRowsToTop = true,
  className = "custom-jasmin-table",
  ...tableProps
}: EditableTableProps<T>) => {
  // Dev-only contract guards. Catch three EditableTable foot-guns: a dead
  // `list` (no `showSearchBar`, so it never auto-fetches — and becomes a
  // double-fetch the moment someone adds it), a dead `baseParams` (only the
  // auto-fetch path reads it), and a `focusIndex` that isn't a real column.
  // Warns once per mount; stripped from production by `drop_console` +
  // `import.meta.env.DEV`.
  const contractWarnedRef = useRef(false);
  useEffect(() => {
    if (!import.meta.env.DEV || contractWarnedRef.current) return;
    contractWarnedRef.current = true;
    if (apiFunctions?.list && !showSearchBar) {
      console.warn(
        "[EditableTable] `apiFunctions.list` is set without `showSearchBar`: the table never auto-fetches, so `list` is dead code (and a latent double-fetch). Remove it, or enable `showSearchBar`.",
      );
    }
    if (
      Object.keys(baseParams).length > 0 &&
      !apiFunctions?.list
    ) {
      console.warn(
        "[EditableTable] `baseParams` is set without `apiFunctions.list`: only the auto-fetch path reads it, so it has no effect. Remove it.",
      );
    }
    if (
      focusIndex &&
      !columns.some((column) => column.dataIndex === focusIndex)
    ) {
      console.warn(
        `[EditableTable] focusIndex "${focusIndex}" is not a column dataIndex — it will silently no-op.`,
      );
    }
  }, [apiFunctions, showSearchBar, baseParams, focusIndex, columns]);

  const { t } = useTranslation();
  const isMobile = useIsMobile();
  const { format } = useNumberFormat();
  const { isModalMode: contextModalMode } = useModal();
  const isModalMode = isMobile
    ? true
    : forceInlineMode
      ? false
      : contextModalMode;

  // `showActions` is the action-column (edit / delete buttons).
  // - Explicit `false` from the caller wins: read-only pages stay read-only.
  // - Explicit `true` wins: forces the column on even when permissions are
  //   restrictive (rare; keeps the door open for legacy callers).
  // - Omitted (the recommended pattern): auto-derive from `permissions`
  //   (`hasRowActions`), so callers don't need to pass both
  //   `permissions={gatedByPermission(...)}` AND `showActions={...}` with the
  //   same condition.
  const effectiveShowActions = showActions ?? hasRowActions(permissions);

  const [isModalVisible, setIsModalVisible] = useState(false);
  const [modalRecord, setModalRecord] = useState<T | null>(null);

  const [pageSize, setPageSize] = useState(10);
  const paginationConfig = pagination
    ? {
        pageSize,
        showSizeChanger: true,
        pageSizeOptions: ["10", "20", "50", "100", "500"],
        onChange: (_page: number, newPageSize: number) => {
          setPageSize(newPageSize);
        },
        locale: { items_per_page: t("table.items_per_page") },
        position: ["topRight" as const, "bottomRight" as const],
      }
    : false;

  const { updatedRowsRef, rememberUpdatedRow } = useUpdatedRows(initialData);

  const {
    form,
    data,
    setDataWithTransform,
    loading,
    setLoading,
    editingKey,
    formErrors,
    saveErrorMessage,
    setSaveErrorMessage,
    deleteErrorMessage,
    setDeleteErrorMessage,
    clickedDataIndex,
    setClickedDataIndex,
    isEditing,
    edit,
    cancel,
    save,
    add,
    deleteRecord,
    recentlyAddedIds,
    recentlyDeletedIds,
  } = useEditableTable<T>({
    apiEndpoints,
    apiFunctions,
    onDataChange,
    focusIndex,
    columns,
    customSave,
    customEdit,
    customDelete,
    customUpdate,
    deleteContext,
    uniqueCheck,
    uniqueCheckMessage,
    uniqueCheckRows,
    autoHandleDates: true,
    onSaveSuccess,
    onDeleteSuccess,
    onRowUpdated: rememberUpdatedRow,
  });

  // Spinner on the data grid reflects BOTH the table's own save/delete work
  // (`loading`) and an externally-owned fetch (`loadingProp`). The edit modal's
  // save button keeps using `loading` only — a parent refetch shouldn't spin
  // the modal's submit.
  const tableLoading = loading || loadingProp;

  const [searchText, setSearchText] = useState("");

  // Surfaces a failed initial-data fetch (the table owns its own fetch when
  // ``showSearchBar`` + ``apiFunctions.list`` / ``apiEndpoints.list`` are set).
  // ``retryNonce`` re-triggers the fetch effect from the Alert's retry button.
  const [fetchErrorMessage, setFetchErrorMessage] = useState<string | null>(
    null,
  );
  const [retryNonce, setRetryNonce] = useState(0);

  // Stable key for the baseParams content — JSON.stringify directly in the
  // dep array would work at runtime but breaks the linter's static check.
  const baseParamsKey = useMemo(() => JSON.stringify(baseParams), [baseParams]);

  // Fetch initial data from API for pages that use showSearchBar.
  //
  // Intentionally narrow deps: this effect should re-fetch ONLY when the
  // params content changes (baseParamsKey). Adding `apiFunctions` /
  // `apiEndpoints` / `onDataChange` would re-fetch on every parent render
  // unless the parent memoises them — most callers don't, so it would loop.
  useEffect(() => {
    if (!showSearchBar || (!apiFunctions?.list && !apiEndpoints.list)) return;

    let cancelled = false;
    const fetchInitialData = async () => {
      try {
        setLoading(true);
        setFetchErrorMessage(null);

        let rows: unknown;

        if (apiFunctions?.list) {
          const params = { ...baseParams } as Record<string, string>;
          const response = await apiFunctions.list(params);
          if (cancelled) return;
          rows = response.data;
        } else {
          const params = new URLSearchParams(
            baseParams as Record<string, string>,
          ).toString();
          const response = await axiosService.get(
            `${apiEndpoints.list}?${params}`,
          );
          if (cancelled) return;
          rows = response.data;
        }

        // The endpoint contract is a bare array of rows. Anything else (a
        // paginated envelope, an error object) would silently render an empty
        // or broken table — surface it via the fetch-error banner instead.
        if (!Array.isArray(rows)) {
          setFetchErrorMessage("Unexpected list response (expected an array)");
          return;
        }

        const transformedData = (rows as T[]).map(
          (item) => ({ ...item, key: item.id }) as T,
        );

        setDataWithTransform(transformedData);

        if (onDataChange) {
          onDataChange(transformedData);
        }
      } catch (error) {
        if (cancelled) return;
        console.error("Error fetching data:", error);
        // Surface the failure inline (the component has no notify util) so the
        // user can tell a failed load from a genuinely empty result and retry,
        // mirroring the save-error Alert below.
        setFetchErrorMessage(
          error instanceof Error ? error.message : String(error),
        );
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    fetchInitialData();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- refetches only when the params' content changes
  }, [baseParamsKey, retryNonce]);

  const handleSearch = useCallback((event: ChangeEvent<HTMLInputElement>) => {
    setSearchText(event.target.value);
  }, []);

  const filteredData = useMemo(() => {
    if (!showSearchBar || !searchText.trim()) return data;
    const lower = searchText.toLowerCase();
    return data.filter((record) => {
      if (record.key === -1 || record.key === "summary-row") return true;
      return columns.some((col) => {
        const val = (record as Record<string, unknown>)[col.dataIndex];
        if (val == null) return false;
        return String(val).toLowerCase().includes(lower);
      });
    });
  }, [data, searchText, showSearchBar, columns]);

  const tableSummary = useCallback(() => {
    if (!summaryRows.length) {
      return null;
    }

    const summaryContent = summaryRows.map(
      (summaryRow: SummaryRow, rowIndex: number) => {
        const rowStyle = summaryRow.style
          ? {
              ...summaryRow.style,
              backgroundColor: `${summaryRow.style.backgroundColor} !important`,
            }
          : {
              backgroundColor:
                rowIndex % 2 === 0
                  ? "var(--color-bg-elevated)"
                  : "var(--color-bg-hover)",
              fontWeight: "bold" as const,
              borderTop:
                rowIndex === 0
                  ? "2px solid var(--color-border)"
                  : "1px solid var(--color-border-subtle)",
            };

        const cellBackgroundColor =
          summaryRow.style?.backgroundColor || rowStyle.backgroundColor;

        return (
          <Table.Summary.Row key={`summary-${rowIndex}`} style={rowStyle}>
            {rowSelection && (
              <StyledSummaryCell
                index={0}
                style={{ backgroundColor: cellBackgroundColor }}
              />
            )}
            {effectiveShowActions && (
              <StyledSummaryCell
                index={rowSelection ? 1 : 0}
                style={{ backgroundColor: cellBackgroundColor }}
              />
            )}

            {(() => {
              let cellIndex =
                (rowSelection ? 1 : 0) + (effectiveShowActions ? 1 : 0);
              const summaryCells: ReactNode[] = [];

              const labelColSpan = summaryRow.summaryLabelColSpan || 1;
              let columnsToSkip = 0;

              const processColumns = (
                cols: EditableColumnConfig<T>[],
                depth = 0,
              ) => {
                cols.forEach((column, columnIndex) => {
                  if (column.dataIndex === "actions") return;
                  if (column.hidden === true) return;

                  if (columnsToSkip > 0) {
                    if (column.children && Array.isArray(column.children)) {
                      columnsToSkip -= column.children.length;
                    } else if (column.dataIndex) {
                      columnsToSkip--;
                    }
                    return;
                  }

                  if (depth === 0 && columnIndex < summaryLabelColumnIndex) {
                    if (column.children && Array.isArray(column.children)) {
                      column.children.forEach(() => {
                        summaryCells.push(
                          <StyledSummaryCell
                            key={`${rowIndex}-empty-${cellIndex}`}
                            index={cellIndex}
                            style={{
                              backgroundColor: cellBackgroundColor,
                            }}
                          />,
                        );
                        cellIndex++;
                      });
                    } else if (column.dataIndex) {
                      summaryCells.push(
                        <StyledSummaryCell
                          key={`${rowIndex}-empty-${cellIndex}`}
                          index={cellIndex}
                          style={{
                            backgroundColor: cellBackgroundColor,
                          }}
                        />,
                      );
                      cellIndex++;
                    }
                    return;
                  }

                  if (column.children && Array.isArray(column.children)) {
                    processColumns(column.children, depth + 1);
                  } else if (column.dataIndex) {
                    const isLabelColumn =
                      depth === 0 && columnIndex === summaryLabelColumnIndex;

                    const shouldShowValue = summaryRow.columns.includes(
                      column.dataIndex,
                    );
                    const value = shouldShowValue
                      ? summaryRow.data[column.dataIndex]
                      : "";

                    const subValue =
                      shouldShowValue && summaryRow.subData
                        ? summaryRow.subData[column.dataIndex]
                        : undefined;

                    const displayValue = isLabelColumn
                      ? summaryRow.label
                      : value !== undefined && value !== null && value !== ""
                        ? typeof value === "number"
                          ? `${format(value, 2)}${
                              summaryRow.suffix ? ` ${summaryRow.suffix}` : ""
                            }`
                          : `${value}${
                              summaryRow.suffix ? ` ${summaryRow.suffix}` : ""
                            }`
                        : "";

                    const subDisplayValue =
                      subValue !== undefined &&
                      subValue !== null &&
                      subValue !== ""
                        ? typeof subValue === "number"
                          ? `${format(subValue, 2)}${summaryRow.subSuffix ? ` ${summaryRow.subSuffix}` : ""}`
                          : `${subValue}${summaryRow.subSuffix ? ` ${summaryRow.subSuffix}` : ""}`
                        : "";

                    const cellColSpan =
                      isLabelColumn && labelColSpan > 1
                        ? labelColSpan
                        : undefined;

                    summaryCells.push(
                      <StyledSummaryCell
                        key={`${rowIndex}-${column.dataIndex}`}
                        index={cellIndex}
                        colSpan={cellColSpan}
                        style={{
                          textAlign: isLabelColumn
                            ? "left"
                            : column.align || "center",
                          paddingLeft: "8px",
                          paddingRight: "8px",
                          backgroundColor: cellBackgroundColor,
                          fontWeight: summaryRow.style?.fontWeight || "bold",
                          borderTop: summaryRow.style?.borderTop,
                          borderBottom: summaryRow.style?.borderBottom,
                          fontSize: summaryRow.style?.fontSize || "1em",
                          ...column.style,
                        }}
                      >
                        <div
                          style={{
                            textAlign: isLabelColumn
                              ? "left"
                              : column.align || "center",
                            color: summaryRow.style?.color,
                          }}
                        >
                          {displayValue}
                          {isLabelColumn && summaryRow.subLabel && (
                            <div
                              style={{
                                fontSize: "0.75em",
                                color: "var(--color-text-tertiary)",
                                fontWeight: "normal",
                              }}
                            >
                              {summaryRow.subLabel}
                            </div>
                          )}
                          {subDisplayValue && (
                            <div
                              style={{
                                fontSize: "0.75em",
                                color: "var(--color-text-tertiary)",
                                fontWeight: "normal",
                              }}
                            >
                              {subDisplayValue}
                            </div>
                          )}
                        </div>
                      </StyledSummaryCell>,
                    );

                    if (isLabelColumn && labelColSpan > 1) {
                      columnsToSkip = labelColSpan - 1;
                    }

                    cellIndex++;
                  }
                });
              };

              processColumns(columns);
              return summaryCells;
            })()}
          </Table.Summary.Row>
        );
      },
    );

    if (summaryPosition === "top") {
      return <Table.Summary fixed="top">{summaryContent}</Table.Summary>;
    }

    return <>{summaryContent}</>;
  }, [
    summaryRows,
    columns,
    effectiveShowActions,
    summaryLabelColumnIndex,
    summaryPosition,
    format,
    rowSelection,
  ]);

  useInitialDataSync({
    initialData,
    pinNewRowsToTop,
    setDataWithTransform,
    recentlyAddedIds,
    recentlyDeletedIds,
    updatedRowsRef,
  });

  const handleModalEdit = useCallback(
    (record: T) => {
      if (!canEditRow(permissions, record)) return;
      setModalRecord(record);
      setIsModalVisible(true);
      edit(record);
    },
    [edit, permissions],
  );

  const handleModalAdd = useCallback(async () => {
    const newRecord = await add();
    if (newRecord) {
      setModalRecord(newRecord);
      setIsModalVisible(true);
    }
  }, [add]);

  const handleModalSave = useCallback(
    async (formValues: Record<string, unknown>) => {
      if (!(await save(modalRecord!.key, formValues))) return;
      setIsModalVisible(false);
      setModalRecord(null);
    },
    [save, modalRecord],
  );

  const handleModalCancel = useCallback(() => {
    cancel();
    setIsModalVisible(false);
    setModalRecord(null);
  }, [cancel]);

  const handleAddClick = useCallback(() => {
    if (isModalMode) {
      handleModalAdd();
    } else {
      add();
    }
  }, [isModalMode, handleModalAdd, add]);

  useAddShortcut(
    Boolean(keyboardAddShortcut && permissions.canAdd),
    isModalVisible ||
      (editingKey !== "" && editingKey !== undefined && editingKey !== null),
    handleAddClick,
  );

  const handleCellClick = useCallback(
    (record: T, dataIndex: string) => {
      if (record.key === "summary-row") return;
      if (!allowsRow(permissions.canEditRecord, record)) return;
      if (isModalMode) {
        handleModalEdit(record);
        return;
      }
      if (permissions.canEdit === false) return;
      if (record.key === editingKey) return;

      if (record.key !== -1) {
        setDataWithTransform((currentData) =>
          currentData.filter((item) => item.key !== -1),
        );
      }
      save(editingKey as Key).then((saved) => {
        // A row whose save failed stays open with its error, or a refused
        // change would look saved; a new row that didn't save is dropped.
        if (!saved && editingKey !== -1) return;
        edit(record);
        setClickedDataIndex(dataIndex);
      });
    },
    [
      permissions,
      isModalMode,
      handleModalEdit,
      editingKey,
      setDataWithTransform,
      save,
      edit,
      setClickedDataIndex,
    ],
  );

  const actionColumn = useMemo(
    () => ({
      title: <span className="sr-only">{t("table.actions")}</span>,
      dataIndex: "actions",
      key: "actions",
      align: "center" as const,
      width: "5em",
      fixed: true as const,
      render: (_: unknown, record: T) => {
        if (record.key === "summary-row") return null;

        const editable = isEditing(record);

        const canEditThisRow = canEditRow(permissions, record);
        const canDeleteRecord = canDeleteRow(permissions, record);

        if (isModalMode) {
          return (
            <Space>
              <Button
                size="small"
                icon={<EditOutlined />}
                onClick={() => handleModalEdit(record)}
                disabled={!canEditThisRow}
                aria-label={t("table.edit")}
              />
              {canDeleteRecord && (
                <Popconfirm
                  title={t("table.delete_confirm")}
                  onConfirm={() => deleteRecord(record.key)}
                  okText={t("table.yes")}
                  cancelText={t("table.no")}
                  icon={null}
                >
                  <Button
                    size="small"
                    icon={<DeleteOutlined />}
                    aria-label={t("table.delete")}
                  />
                </Popconfirm>
              )}
            </Space>
          );
        }

        return editable ? (
          <Space>
            <Button
              size="small"
              icon={<SaveOutlined />}
              onClick={() => save(record.key)}
              aria-label={t("table.save")}
            />
            <Popconfirm
              title={t("table.cancel_confirm")}
              onConfirm={cancel}
              okText={t("table.yes")}
              cancelText={t("table.no")}
              icon={null}
            >
              <Button
                size="small"
                icon={<UndoOutlined />}
                aria-label={t("table.cancel")}
              />
            </Popconfirm>
          </Space>
        ) : (
          <Space>
            <Button
              size="small"
              icon={<EditOutlined />}
              onClick={() => handleCellClick(record, columns[0]?.dataIndex)}
              disabled={!canEditThisRow}
              aria-label={t("table.edit")}
            />
            {canDeleteRecord && (
              <Popconfirm
                title={t("table.delete_confirm")}
                onConfirm={() => deleteRecord(record.key)}
                okText={t("table.yes")}
                cancelText={t("table.no")}
                icon={null}
              >
                <Button
                  size="small"
                  icon={<DeleteOutlined />}
                  aria-label={t("table.delete")}
                />
              </Popconfirm>
            )}
          </Space>
        );
      },
    }),
    [
      isEditing,
      permissions,
      isModalMode,
      handleModalEdit,
      deleteRecord,
      t,
      save,
      cancel,
      handleCellClick,
      columns,
    ],
  );

  const enhancedColumns = useMemo(
    () => [
      ...(effectiveShowActions ? [actionColumn] : []),
      ...enhanceCheckboxColumns(columns).map((col) => {
        const processColumn = (
          column: EditableColumnConfig<T>,
        ): EditableColumnConfig<T> => {
          if (column.children && Array.isArray(column.children)) {
            return {
              ...column,
              render:
                column.render ||
                (column.foreignKey ? undefined : column.render),
              children: column.children.map(processColumn),
            };
          }

          const withSorter = withAutoSorter(column);
          return {
            ...withSorter,
            showSorterTooltip: withSorter.showSorterTooltip ?? false,
            onCell: (record: T) => {
              // A FUNCTION `disabled` is re-evaluated LIVE inside EditableCell
              // (reactiveDisabled, against the in-edit form values) so it can
              // react to a sibling cell changing mid-edit — e.g. a seller cell
              // that unlocks once a purchased share_article is picked. Baking
              // the static (saved-record) result into the `disabled` prop here
              // would OR with the live one and pin the cell disabled. Only a
              // boolean `disabled` is genuinely static.
              const isDisabled =
                typeof column.disabled === "function" ? false : column.disabled;

              return {
                record,
                dataIndex: column.dataIndex,
                title: column.title,
                editing: isModalMode
                  ? false
                  : isEditing(record) &&
                    column.editable !== false &&
                    permissions.canEdit !== false,
                inputType: column.inputType,
                options: column.options,
                suffix: column.suffix,
                formErrors,
                onCellClick: handleCellClick,
                columns,
                form,
                shouldFocus:
                  column.dataIndex === (clickedDataIndex || focusIndex),
                disabled: isDisabled || permissions.canEdit === false,
                required: column.required,
                save,
              };
            },
          };
        };

        return processColumn(col);
      }),
    ],
    [
      effectiveShowActions,
      actionColumn,
      columns,
      isModalMode,
      isEditing,
      permissions,
      formErrors,
      handleCellClick,
      form,
      clickedDataIndex,
      focusIndex,
      save,
    ],
  );

  const { selectedKeys, changeSelection } = useRowSelectionState({
    rows: data,
    selectedRowKeys,
    onSelectedRowsChange,
  });

  const tableRowSelection = rowSelection
    ? {
        type: (rowSelection.type || "checkbox") as "checkbox" | "radio",
        selectedRowKeys: selectedKeys,
        onChange: changeSelection,
        onSelect: rowSelection.onSelect,
        onSelectAll: rowSelection.onSelectAll,
        getCheckboxProps:
          rowSelection.getCheckboxProps ||
          ((record: T) => ({
            disabled: record.key === -1 || record.key === "summary-row",
          })),
        ...rowSelection,
      }
    : undefined;

  const { scroll: propsScroll, ...otherTableProps } = tableProps;

  const propsScrollX = propsScroll?.x;
  const computedScrollX = useMemo(() => {
    if (propsScrollX !== undefined) return propsScrollX;
    if (!autoScrollX) return undefined;
    return calculateTableScrollWidth(columns);
  }, [propsScrollX, autoScrollX, columns]);

  return (
    <div>
      {fetchErrorMessage && (
        // Banner shown when the table's own initial-data fetch failed. The
        // retry button re-runs the fetch effect; dismissible with ×.
        <Alert
          type="error"
          showIcon
          closable
          message={t("table.load_failed_title")}
          description={`${fetchErrorMessage} — ${t("table.load_failed_hint")}`}
          action={
            <Button size="small" onClick={() => setRetryNonce((n) => n + 1)}>
              {t("table.retry")}
            </Button>
          }
          onClose={() => setFetchErrorMessage(null)}
          className="editable-table-banner"
        />
      )}
      {saveErrorMessage && (
        // Banner shown when a save was rejected by a unique-check or by the
        // backend. Sticks until the user starts editing again, cancels, or
        // saves successfully; can also be dismissed with the × icon. The
        // per-cell red borders come from `formErrors` and are unrelated.
        <Alert
          type="error"
          showIcon
          closable
          message={t("table.save_failed_title")}
          description={`${saveErrorMessage} — ${t("table.save_failed_hint")}`}
          onClose={() => setSaveErrorMessage(null)}
          className="editable-table-banner"
        />
      )}
      {deleteErrorMessage && (
        <Alert
          type="error"
          showIcon
          closable
          message={t("table.delete_failed_title")}
          description={deleteErrorMessage}
          onClose={() => setDeleteErrorMessage(null)}
          className="editable-table-banner"
        />
      )}
      {isMobile ? (
        <>
          {showSearchBar && (
            <TableSearchInput value={searchText} onChange={handleSearch} mobile />
          )}
          <MobileCardList
            data={filteredData}
            columns={columns}
            loading={tableLoading}
            permissions={permissions}
            onEdit={handleModalEdit}
            onAdd={handleModalAdd}
            onDelete={deleteRecord}
            renderMobileCard={renderMobileCard}
          />
        </>
      ) : (
        <>
          <div
            className="flex-between"
            style={{
              marginBottom: 8,
              marginTop: 24,
            }}
          >
            <div>
              {permissions.canAdd && (
                <Button
                  size="small"
                  icon={<PlusOutlined aria-hidden />}
                  aria-label={t("table.add_record")}
                  title={t("table.add_record")}
                  onClick={handleAddClick}
                  style={{ width: "2em" }}
                />
              )}
            </div>
            <div>
              {showSearchBar && (
                <TableSearchInput value={searchText} onChange={handleSearch} />
              )}
            </div>
          </div>

          <Form form={form} component={false}>
            <Table
              components={{
                body: {
                  cell: EditableCell,
                },
              }}
              columns={enhancedColumns as ColumnsType<T>}
              dataSource={filteredData}
              loading={tableLoading}
              size={size}
              pagination={paginationConfig}
              rowSelection={tableRowSelection}
              summary={tableSummary}
              locale={{
                emptyText: <EmptyHint>{t("table.no_data")}</EmptyHint>,
              }}
              scroll={{ x: computedScrollX }}
              className={className}
              {...otherTableProps}
            />
          </Form>
        </>
      )}

      <EditableModal
        visible={isModalVisible}
        onCancel={handleModalCancel}
        onSave={handleModalSave}
        record={modalRecord}
        columns={columns}
        loading={loading}
        errorMessage={saveErrorMessage}
        customEdit={customEdit}
        focusIndex={focusIndex}
        uniqueCheck={uniqueCheck}
        uniqueCheckMessage={uniqueCheckMessage}
        data={data}
      />
    </div>
  );
};

export default EditableTable;
