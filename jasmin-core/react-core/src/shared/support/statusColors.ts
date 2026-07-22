import type { TicketStatusEnum } from "@shared/api/generated/models";

/** AntD Tag colors per ticket status — shared by the list rows + detail view. */
const STATUS_TAG_COLOR: Record<string, string> = {
  open: "blue",
  in_progress: "gold",
  resolved: "green",
  closed: "default",
};

export function statusTagColor(status?: TicketStatusEnum): string {
  return STATUS_TAG_COLOR[status ?? ""] ?? "default";
}
