import { Fragment, isValidElement, useMemo } from "react";
import type { Key, ReactNode } from "react";
import { Button, Space, Popconfirm, Checkbox, Tag, Empty, Spin } from "antd";
import {
  EditOutlined,
  DeleteOutlined,
  PlusOutlined,
  InfoCircleOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import type {
  EditableColumnConfig,
  TablePermissions,
  TableRecord,
  SelectOption,
} from "./types";
import "./MobileCardList.css";

/** Columns whose dataIndex starts with one of these prefixes are shown as tags. */
const TAG_PREFIXES = ["variation_", "offer_group_", "for_all_"];
const isTagColumn = (dataIndex: string) =>
  TAG_PREFIXES.some((p) => dataIndex.startsWith(p));

/** Flatten grouped (parent → children) columns into a flat list. */
function flattenColumns<T extends TableRecord>(
  cols: EditableColumnConfig<T>[],
): EditableColumnConfig<T>[] {
  const flat: EditableColumnConfig<T>[] = [];
  for (const col of cols) {
    if (col.children && Array.isArray(col.children)) {
      flat.push(...flattenColumns(col.children));
    } else if (col.dataIndex && col.dataIndex !== "actions") {
      flat.push(col);
    }
  }
  return flat;
}

/** Resolve a display value for a column. */
function resolveDisplay<T extends TableRecord>(
  col: EditableColumnConfig<T>,
  record: T,
): ReactNode {
  const raw = (record as Record<string, unknown>)[col.dataIndex];

  // Foreign-key → show the display field
  if (col.foreignKey) {
    const display = (record as Record<string, unknown>)[
      col.foreignKey.displayField
    ];
    if (display) return String(display);
  }

  // Select → map value to label
  if (col.inputType === "select" && col.options) {
    const opts =
      typeof col.options === "function"
        ? col.options(record)
        : col.options;
    const match = (opts as SelectOption[]).find(
      (o) => String(o.value) === String(raw),
    );
    if (match) return match.label;
  }

  // Boolean / checkbox
  if (col.inputType === "checkbox" || col.inputType === "switch") {
    return raw ? "✓" : "";
  }

  if (raw === null || raw === undefined || raw === "") return "–";
  return String(raw);
}

/** Extract a short title string from a ReactNode. */
function titleText(node: ReactNode): string {
  if (typeof node === "string") return node;
  if (typeof node === "number") return String(node);
  if (isValidElement(node)) {
    const { children } = node.props as { children?: ReactNode };
    if (children) return titleText(children);
  }
  return "";
}

// ─────────────────────────────────────────────────────────────────────────────

interface MobileCardListProps<T extends TableRecord> {
  data: T[];
  columns: EditableColumnConfig<T>[];
  loading?: boolean;
  permissions?: TablePermissions<T>;
  onEdit: (record: T) => void;
  onAdd: () => void;
  onDelete: (key: Key) => void;
  /** Columns whose dataIndex appears here are shown in the card summary. */
  primaryFields?: string[];
  /** Override default card rendering per record. */
  renderMobileCard?: (record: T, onEdit: (record: T) => void) => ReactNode;
}

function MobileCardList<T extends TableRecord>({
  data,
  columns,
  loading = false,
  permissions = {},
  onEdit,
  onAdd,
  onDelete,
  primaryFields,
  renderMobileCard,
}: MobileCardListProps<T>) {
  const { t } = useTranslation();
  const flat = useMemo(() => flattenColumns(columns), [columns]);

  // Determine which columns are "primary" (shown in card body)
  // and which are "tags" (boolean flags shown as small tags).
  const { primary, tags } = useMemo(() => {
    if (primaryFields) {
      return {
        primary: flat.filter(
          (c) =>
            primaryFields.includes(c.dataIndex) && !isTagColumn(c.dataIndex),
        ),
        tags: flat.filter((c) => isTagColumn(c.dataIndex)),
      };
    }
    // Auto-detect: first select/FK column is the title, then amount/unit/size
    return {
      primary: flat.filter(
        (c) =>
          !isTagColumn(c.dataIndex) &&
          c.inputType !== "checkbox" &&
          c.inputType !== "switch" &&
          !c.hidden &&
          !c.hideInModal,
      ),
      tags: flat.filter((c) => isTagColumn(c.dataIndex)),
    };
  }, [flat, primaryFields]);

  if (loading) {
    return (
      <div className="mobile-card-list-loading">
        <Spin />
      </div>
    );
  }

  const activeData = data.filter((r) => r.key !== -1 && r.key !== "summary-row");

  return (
    <div className="mobile-card-list">
      {/* Add button */}
      {permissions.canAdd && (
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={onAdd}
          block
          className="mobile-card-add-btn"
        >
          {t("table.add_record")}
        </Button>
      )}

      {activeData.length === 0 ? (
        <div className="mobile-card-empty" style={{ textAlign: "center", padding: "24px 0", color: "var(--color-text-muted)" }}>
          {t("table.no_data")}
        </div>
      ) : (
        activeData.map((record) => {
          if (renderMobileCard) {
            return (
              <Fragment key={String(record.key)}>
                {renderMobileCard(record, onEdit)}
              </Fragment>
            );
          }

          const canEditRecord =
            permissions.canEdit !== false &&
            (typeof permissions.canEditRecord === "function"
              ? permissions.canEditRecord(record)
              : permissions.canEditRecord !== false);

          const canDeleteRecord =
            permissions.canDelete !== false &&
            (typeof permissions.canDeleteRecord === "function"
              ? permissions.canDeleteRecord(record)
              : permissions.canDeleteRecord !== false);

          // First primary field is the "title"
          const titleCol = primary[0];
          const titleValue = titleCol
            ? resolveDisplay(titleCol, record)
            : String(record.key);

          // Is finalized?
          const isFinalized = !!record.is_finalized;

          // Active boolean tags
          const activeTags = tags.filter(
            (c) => !!(record as Record<string, unknown>)[c.dataIndex],
          );

          return (
            // role + tabIndex + onKeyDown are all set together when the row is
            // editable (and all absent otherwise), so this stays accessible.
            <div
              key={String(record.key)}
              className={`mobile-card-item ${isFinalized ? "mobile-card-finalized" : ""}`}
              role={canEditRecord ? "button" : undefined}
              tabIndex={canEditRecord ? 0 : undefined}
              onClick={() => canEditRecord && onEdit(record)}
              onKeyDown={canEditRecord ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onEdit(record); } } : undefined}
            >
              {/* Left: content */}
              <div className="mobile-card-content">
                <div className="mobile-card-title">
                  {/* A11Y-10: finalized state is otherwise colour-only —
                      role=img + aria-label exposes it to screen readers with no
                      visual change. */}
                  {isFinalized && (
                    <span
                      className="mobile-card-finalized-dot"
                      role="img"
                      aria-label={t("commissioning.finalized")}
                    />
                  )}
                  {titleValue}
                </div>

                {/* Secondary fields */}
                <div className="mobile-card-details">
                  {primary.slice(1, 4).map((col) => {
                    const val = resolveDisplay(col, record);
                    if (val === "–") return null;
                    return (
                      <span key={col.dataIndex} className="mobile-card-detail">
                        <span className="mobile-card-detail-label">
                          {titleText(col.title)}:
                        </span>{" "}
                        {val}
                      </span>
                    );
                  })}
                </div>

                {/* Tag pills */}
                {activeTags.length > 0 && (
                  <div className="mobile-card-tags">
                    {activeTags.map((c) => (
                      <Tag key={c.dataIndex} className="mobile-card-tag">
                        {titleText(c.title)}
                      </Tag>
                    ))}
                  </div>
                )}
              </div>

              {/* Right: actions. Wrapper only stops the card's click/keydown
                  (edit) from firing when an inner action is activated — not a
                  control itself. */}
              {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions -- propagation boundary around interactive children */}
              <div
                className="mobile-card-actions"
                onClick={(e) => e.stopPropagation()}
                onKeyDown={(e) => e.stopPropagation()}
              >
                <Space direction="vertical" size={4}>
                  <Button
                    size="small"
                    type="text"
                    icon={<InfoCircleOutlined />}
                    onClick={() => onEdit(record)}
                    disabled={!canEditRecord}
                    aria-label={t("table.edit")}
                  />
                  {canDeleteRecord && (
                    <Popconfirm
                      title={t("table.delete_confirm")}
                      onConfirm={() => onDelete(record.key)}
                      okText={t("table.yes")}
                      cancelText={t("table.no")}
                      icon={null}
                    >
                      <Button
                        size="small"
                        type="text"
                        danger
                        icon={<DeleteOutlined />}
                        aria-label={t("table.delete")}
                      />
                    </Popconfirm>
                  )}
                </Space>
              </div>
            </div>
          );
        })
      )}
    </div>
  );
}

export default MobileCardList;
