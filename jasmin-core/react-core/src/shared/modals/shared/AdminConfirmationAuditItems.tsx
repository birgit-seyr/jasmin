import type { ReactElement } from "react";
import { Descriptions, Typography } from "antd";
import type { TFunction } from "i18next";
import type { AdminConfirmableRecord } from "./adminConfirmation";

const { Text } = Typography;

/**
 * Returns the two trailing "audit" Description.Items shared by the admin
 * confirmation modals (who confirmed, when). Returned as an array so antd's
 * <Descriptions> sees them as direct Descriptions.Item children.
 *
 * ``formatDateTime`` is passed in (rather than imported as a hook here)
 * because this helper is a plain function called inside the render
 * tree — callers pull the formatter from ``useTimeFormat()`` and pass
 * it through so the audit timestamp honours the tenant's
 * ``time_format`` / ``date_format`` settings.
 */
export function adminConfirmationAuditItems(
  record: AdminConfirmableRecord,
  t: TFunction,
  formatDateTime: (value: string | null | undefined) => string | null,
): ReactElement[] {
  return [
    <Descriptions.Item
      key="admin_confirmed_by"
      label={
        <Text type="secondary" className="text-label-sm">
          {t("members.admin_confirmed_by")}
        </Text>
      }
    >
      <span className="text-secondary">
        {record.admin_confirmed_by_name || "-"}
      </span>
    </Descriptions.Item>,
    <Descriptions.Item
      key="admin_confirmed_at"
      label={
        <Text type="secondary" className="text-label-sm">
          {t("members.admin_confirmed_at")}
        </Text>
      }
    >
      <span className="text-secondary">
        {record.admin_confirmed_at
          ? formatDateTime(record.admin_confirmed_at)
          : "-"}
      </span>
    </Descriptions.Item>,
  ];
}

