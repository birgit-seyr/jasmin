import { Checkbox } from "antd";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import "./CheckboxMultiSelectList.css";

export interface CheckboxMultiSelectListItem {
  /** Stable identity used in ``selectedKeys``. */
  key: string;
  /** Rendered beside the checkbox. */
  label: ReactNode;
}

export interface CheckboxMultiSelectListProps {
  items: CheckboxMultiSelectListItem[];
  /** Controlled selection — the parent owns and seeds it. */
  selectedKeys: string[];
  onChange: (keys: string[]) => void;
  /** Render the "select all" header row with an indeterminate tri-state. */
  withSelectAll?: boolean;
  /** Overrides the default ``common.select_all`` label. */
  selectAllLabel?: ReactNode;
}

/**
 * Controlled "select-all + scrollable checkbox list" block. The parent keeps
 * ``selectedKeys`` in its own state (so it can seed / reset it however it
 * likes) and receives the next selection through ``onChange``. Shared by the
 * CSV column picker and the SendOffers reseller picker.
 */
export default function CheckboxMultiSelectList({
  items,
  selectedKeys,
  onChange,
  withSelectAll = false,
  selectAllLabel,
}: CheckboxMultiSelectListProps) {
  const { t } = useTranslation();

  const allSelected = selectedKeys.length === items.length;
  const noneSelected = selectedKeys.length === 0;

  const toggleAll = () =>
    onChange(allSelected ? [] : items.map((item) => item.key));

  const toggle = (key: string) =>
    onChange(
      selectedKeys.includes(key)
        ? selectedKeys.filter((k) => k !== key)
        : [...selectedKeys, key],
    );

  return (
    <>
      {withSelectAll && (
        <div className="checkbox-multi-select__all">
          <Checkbox
            checked={allSelected}
            indeterminate={!allSelected && !noneSelected}
            onChange={toggleAll}
          >
            <strong>{selectAllLabel ?? t("common.select_all")}</strong>
          </Checkbox>
        </div>
      )}
      <div className="checkbox-multi-select__list">
        {items.map((item) => (
          <div key={item.key} className="checkbox-multi-select__item">
            <Checkbox
              checked={selectedKeys.includes(item.key)}
              onChange={() => toggle(item.key)}
            >
              {item.label}
            </Checkbox>
          </div>
        ))}
      </div>
    </>
  );
}
