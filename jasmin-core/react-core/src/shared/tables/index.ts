export { default as EditableTable } from './BasicEditableTable';
export { adminConfirmationColumn } from './adminConfirmationColumn';
export type { AdminStatusVariant } from './adminConfirmationColumn';
export { wrapApiFunctions } from './BasicEditableTable/wrapApiFunctions';
export type { RawApiFunctions } from './BasicEditableTable/wrapApiFunctions';
export {
  READ_ONLY_PERMISSION,
  gatedByPermissionOnlyEdit,
  gatedByPermission,
  isUnprotectedRow,
  permissionsWithDeletable,
} from './tablePermissions';
