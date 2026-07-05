import type { ShareDeliveryOverview } from "@shared/api/generated/models";
import type { TableRecord } from "@shared/tables/BasicEditableTable/types";

/**
 * Shape of a Subscription row as it flows through the Abos page's
 * EditableTable. Pulled out of ``Abos.tsx`` to keep the page file
 * focused on glue + JSX. Field meanings track the backend
 * ``Subscription`` serializer's read view; many fields are
 * annotated (``*_string``, ``*_name``) and exist only on the read
 * side. Keep optional on every field — the placeholder
 * ``key === -1`` row is mostly empty until the office types into it.
 */
export interface AboRecord extends TableRecord {
  // Renewal-chain identity. ``subscription_number`` is shared across a renewal
  // chain, ``renewal_generation`` is the position in it (0 = original term);
  // ``renewal_display_id`` renders them as ``1`` / ``1a`` / ``1b``. Sort by the
  // (number, generation) pair for ``1, 1a, 1b, 2, …`` order.
  subscription_number?: number | null;
  renewal_generation?: number;
  renewal_display_id?: string;
  member?: string;
  member_string?: string;
  share_type_variation?: string;
  share_type_variation_string?: string;
  // True when the variation bills per opted-in delivery (on-off), not every
  // period — drives the "on-off" chip next to the variation name.
  requires_optin?: boolean;
  is_trial?: boolean;
  quantity?: number;
  price_per_delivery?: string;
  valid_from?: string;
  valid_until?: string | null;
  cancelled_effective_at?: string | null;
  cancelled_at?: string | null;
  // The MEMBER's own cancellation stamp (source="member.cancelled_at"), not the
  // subscription's — drives the struck-through/muted row styling for abos of an
  // exited member.
  member_cancelled_at?: string | null;
  // Wire sends the annotated day_number as a NUMBER (0 = Monday); older code
  // assumed string. Consumers must null-check explicitly (0 is falsy!).
  delivery_day_number?: number | string | null;
  delivery_station_name?: string;
  payment_cycle?: string;
  payment_cycle_name?: string;
  default_delivery_station_day?: string | null;
  default_delivery_station_day_string?: string;
  admin_confirmed?: boolean;
  admin_rejected_at?: string | null;
  admin_rejection_reason?: string | null;
  // Waiting-list offer state (WaitingListAbos): PENDING queued row, or
  // SPOT_AVAILABLE once the office has offered a freed spot and is awaiting the
  // member's magic-link response (with ``notification_expires_at``).
  waiting_list_status?: string | null;
  waiting_list_reason?: string | null;
  notification_expires_at?: string | null;
  isEditing?: boolean;
  automatically_renewed_at?: string | null;
  duration_in_weeks?: number;
  display_id?: string;
  email?: string;
  member_first_name?: string;
  member_last_name?: string;
  pickup_name?: string | null;
  admin_confirmed_by_name?: string;
  admin_confirmed_at?: string | null;
  created_at?: string | null;
  created_by_name?: string | null;
  updated_at?: string | null;
  updated_by_name?: string | null;
  cancelled_by_name?: string | null;
  expires_at?: string | null;
  accepted_at?: string | null;
  invited_by_name?: string | null;
  paid_at?: string | null;
}

/**
 * Shape of a ShareDelivery row as it flows through the ShareDeliveries
 * page's EditableTable: the generated overview serializer fields (all
 * optional — the placeholder ``key === -1`` row starts empty) plus the
 * annotated station-day label the foreignKey column displays.
 */
export type ShareDeliveryRecord = TableRecord &
  Partial<ShareDeliveryOverview> & {
    delivery_station_day_string?: string;
  };
