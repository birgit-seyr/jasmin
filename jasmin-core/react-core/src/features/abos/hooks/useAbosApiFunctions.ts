import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  commissioningAbosCreate,
  commissioningAbosDestroy,
  commissioningAbosPartialUpdate,
} from "@shared/api/generated/commissioning/commissioning";
import type { Subscription } from "@shared/api/generated/models";
import type {
  ApiFunctions,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { wrapApiFunctions } from "@shared/tables/BasicEditableTable/wrapApiFunctions";
import { notify } from "@shared/utils";
import { getErrorCode } from "@shared/utils/apiError";

const overCapacityCode = (error: unknown): string | null => {
  const code = getErrorCode(error);
  return code === "share_type_variation.over_capacity" ||
    code === "delivery_station.over_capacity"
    ? code
    : null;
};

/**
 * The Abos grid's EditableTable api functions.
 *
 * A sold-out variation / full station-day 409s a normal save. Don't dead-end
 * the office — redo the save as a waiting-list entry (same as the member
 * subscribe modal; the backend records WHY on the waiting-list page), then
 * invalidate so the now-waiting-listed row LEAVES this (on_waiting_list=false)
 * grid instead of lingering as a phantom draft that inflates the
 * pending-confirmation count.
 *
 * There is no retry while the tenant's waiting list is off, or while onboarding
 * mode is on: the office is then entering subscriptions that already run, so
 * the capacity error shows instead of the row silently becoming a waiting-list
 * entry.
 *
 * No ``list``: the page owns the data via ``useCommissioningAbosList`` (passed
 * as ``initialData``). Supplying ``list`` would make EditableTable double-fetch
 * the same endpoint (it auto-fetches when ``showSearchBar`` +
 * ``apiFunctions.list`` are both set).
 */
export function useAbosApiFunctions({
  invalidateData,
  allowsWaitingList,
  onboardingMode,
}: {
  invalidateData: () => void;
  allowsWaitingList: boolean;
  onboardingMode: boolean;
}): ApiFunctions {
  const { t } = useTranslation();

  return useMemo<ApiFunctions>(() => {
    const retryableCode = (error: unknown): string | null =>
      allowsWaitingList && !onboardingMode ? overCapacityCode(error) : null;
    const notifyWaitingListed = (code: string) =>
      notify.info(
        t(
          code === "share_type_variation.over_capacity"
            ? "abos.waiting_listed_variation_full"
            : "abos.waiting_listed_station_full",
        ),
      );
    return wrapApiFunctions<Subscription & TableRecord>({
      create: async (data) => {
        try {
          return await commissioningAbosCreate(data);
        } catch (error) {
          const code = retryableCode(error);
          if (!code) throw error;
          const created = await commissioningAbosCreate({
            ...data,
            on_waiting_list: true,
          });
          notifyWaitingListed(code);
          invalidateData();
          return created;
        }
      },
      update: async (id, data) => {
        try {
          return await commissioningAbosPartialUpdate(id, data);
        } catch (error) {
          const code = retryableCode(error);
          if (!code) throw error;
          const updated = await commissioningAbosPartialUpdate(id, {
            ...data,
            on_waiting_list: true,
          });
          notifyWaitingListed(code);
          invalidateData();
          return updated;
        }
      },
      delete: (id) => commissioningAbosDestroy(id),
    });
  }, [t, invalidateData, allowsWaitingList, onboardingMode]);
}
