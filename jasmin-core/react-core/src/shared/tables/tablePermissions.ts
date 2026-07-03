import type { TablePermissions } from "./BasicEditableTable/types";

export const READ_ONLY_PERMISSION: TablePermissions = {
  canAdd: false,
  canEdit: false,
  canDelete: false,
} as const;

// Helper for the very common "one boolean gates all three CRUD ops"
// pattern (e.g. `!isPast && isOffice`). The returned object is still
// fresh per call — callers must wrap in `useMemo` if `condition`
// depends on render state.
export const gatedByPermission = (condition: boolean): TablePermissions => ({
  canAdd: condition,
  canEdit: condition,
  canDelete: condition,
});

export const gatedByPermissionOnlyEdit = (condition: boolean): TablePermissions => ({
  canAdd: false,
  canEdit: condition,
  canDelete: false,
});

// Row-level delete guard shared across the editable list pages: a row is
// deletable unless it's the unsaved new-row sentinel (key === -1 / no id) or
// the backend marked it protected (`can_be_deleted === false`).
export const isUnprotectedRow = (record: Record<string, unknown>): boolean =>
  record.key === -1 || !record.id || record.can_be_deleted !== false;

// `gatedByPermission` plus the shared `canDeleteRecord` row guard — the exact
// combination ~9 list pages built inline. Wrap in `useMemo` if `condition`
// depends on render state.
export const permissionsWithDeletable = (
  condition: boolean,
): TablePermissions => ({
  ...gatedByPermission(condition),
  canDeleteRecord: isUnprotectedRow,
});
