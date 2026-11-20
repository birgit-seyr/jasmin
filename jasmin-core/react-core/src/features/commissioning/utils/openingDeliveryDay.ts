import dayjs from "dayjs";
import { nextIsoWeek } from "@shared/utils";

/**
 * The delivery day the resellers' pages open on: today from Monday to
 * Thursday, and next week's Monday from Friday on, when this week's deliveries
 * are packed.
 */
export function openingDeliveryDay(): { year: number; week: number; day: number } {
  const today = dayjs();
  const year = today.isoWeekYear();
  const week = today.isoWeek();
  const weekday = today.isoWeekday();
  if (weekday < 5) return { year, week, day: weekday - 1 };
  return { ...nextIsoWeek(year, week), day: 0 };
}
