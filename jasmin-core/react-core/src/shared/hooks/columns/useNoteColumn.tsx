import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import type {
  EditableColumnConfig,
  InputType,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";

interface NoteColumnOptions {
  width?: string;
  inputType?: InputType;
  disabled?: EditableColumnConfig<TableRecord>["disabled"];
  className?: string;
  render?: EditableColumnConfig<TableRecord>["render"];
  pdf?: EditableColumnConfig<TableRecord>["pdf"];
}

export const useNoteColumn = ({
  width,
  inputType,
  disabled,
  className,
  render,
  pdf,
}: NoteColumnOptions = {}) => {
  const { t } = useTranslation();

  // Destructured primitives/refs are individually compared by React, so this
  // memo only re-runs when something the caller actually changed differs.
  // Don't depend on the whole options object: callers like
  // `useNoteColumn({ inputType: "optional" })` allocate a fresh object
  // every render, which would invalidate the memo every render.
  const noteColumn = useMemo<EditableColumnConfig<TableRecord>>(
    () => ({
      title: <>{t("commissioning.note")}</>,
      dataIndex: "note",
      key: "note",
      inputType: inputType ?? "text",
      required: false,
      width: width ?? "16em",
      ...(disabled !== undefined ? { disabled } : {}),
      ...(className !== undefined ? { className } : {}),
      ...(render !== undefined ? { render } : {}),
      ...(pdf !== undefined ? { pdf } : {}),
    }),
    [t, inputType, width, disabled, className, render, pdf],
  );

  return { noteColumn };
};
