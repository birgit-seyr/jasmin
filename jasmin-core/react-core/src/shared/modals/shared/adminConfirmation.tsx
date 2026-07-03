import type { ReactNode } from "react";
import {
  CheckCircleOutlined,
  ExclamationCircleOutlined,
} from "@ant-design/icons";
import type { TFunction } from "i18next";

export interface AdminConfirmableRecord {
  admin_confirmed?: boolean;
  // Nullable to match the canonical AboRecord/MemberRecord (the read
  // serializers emit `null`); only consumed via a truthy check.
  cancelled_at?: string | null;
  admin_confirmed_by_name?: string;
  admin_confirmed_at?: string | null;
  [key: string]: unknown;
}

export interface AdminConfirmationStatus {
  text: string;
  color: string;
  icon: ReactNode;
}

/**
 * Three-branch admin confirmation status used by abos and members:
 * confirmed → green, cancelled → red, otherwise pending → orange.
 */
export function getAdminConfirmationStatus(
  record: AdminConfirmableRecord | null | undefined,
  t: TFunction,
): AdminConfirmationStatus | null {
  if (!record) return null;
  if (record.admin_confirmed) {
    return {
      text: t("members.admin_confirmed"),
      color: "green",
      icon: <CheckCircleOutlined />,
    };
  }
  if (record.cancelled_at) {
    return {
      text: t("members.cancelled"),
      color: "red",
      icon: <ExclamationCircleOutlined />,
    };
  }
  return {
    text: t("members.admin_pending"),
    color: "orange",
    icon: <ExclamationCircleOutlined />,
  };
}
