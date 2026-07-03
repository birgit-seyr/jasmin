import type { LinkedUserInfo } from "@hooks/modals/useUserInfoModal";
import type { Member } from "@shared/api/generated/models";
import type { TableRecord } from "@shared/tables/BasicEditableTable/types";

/**
 * Shape of a Member row as it flows through the member-admin EditableTables
 * and the confirm/reject modals: the full generated ``Member`` read shape
 * (every field optional — the placeholder ``key === -1`` add-row is mostly
 * empty until the office types into it) plus the table-only ``key``.
 *
 * Two deliberate narrows on top of ``Partial<Member>``:
 *  - ``linked_user_info`` — the schema models it as an untyped JSON blob;
 *    narrowed to the shared ``LinkedUserInfo`` shape that the user-status
 *    column and ``UserInfoModal`` read.
 *  - ``admin_confirmed_by_name`` — narrowed from ``string | null`` so rows
 *    stay assignable to the shared ``AdminConfirmableRecord`` consumers
 *    (``getAdminConfirmationStatus`` / the audit items), which declare the
 *    name as optional ``string`` and only ever read it truthily.
 */
export type MemberRecord = TableRecord &
  Partial<Member> & {
    linked_user_info?: LinkedUserInfo | null;
    admin_confirmed_by_name?: string;
  };
