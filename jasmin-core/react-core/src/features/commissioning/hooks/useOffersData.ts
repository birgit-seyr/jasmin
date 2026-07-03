/**
 * Data sources for the Offers page.
 *
 * Owns the offers list + sending-status queries (and their
 * invalidation), the share-article option source (price info pinned
 * to the selected week's Monday), the offer-group lookups, and the
 * derived flags the page renders from (``allFinalized``,
 * ``resellersForPdf``). The page component only holds UI state
 * (selectors, modals, row selection) and rendering.
 */

import { useQueryClient } from "@tanstack/react-query";
import dayjs from "dayjs";
import { useCallback, useMemo } from "react";
import {
  getCommissioningOfferSendingStatusListQueryKey,
  getCommissioningOffersListQueryKey,
  useCommissioningOfferSendingStatusList,
  useCommissioningOffersList,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningOfferSendingStatusListParams,
  CommissioningOffersListParams,
} from "@shared/api/generated/models";
import type { TableRecord } from "@shared/tables/BasicEditableTable/types";
import { useInvalidateAfterTableMutation } from "@hooks/useInvalidateAfterTableMutation";
import { useOfferGroups } from "./useOfferGroups";
import { useShareArticles } from "./useShareArticles";

export function useOffersData({
  selectedYear,
  selectedWeek,
  selectedOfferGroup,
  usePersonalizedOffers,
}: {
  selectedYear: number;
  selectedWeek: number;
  selectedOfferGroup: string | null;
  usePersonalizedOffers: boolean;
}) {
  const queryClient = useQueryClient();

  const mondayOfSelectedWeek = useMemo(() => {
    return dayjs()
      .year(selectedYear)
      .isoWeek(selectedWeek)
      .startOf("isoWeek")
      .format("YYYY-MM-DD");
  }, [selectedYear, selectedWeek]);

  const shareArticleFilters = useMemo(
    () => ({
      is_active: true,
      is_sold_to_resellers: true,
      get_price_info: true,
      price_date: mondayOfSelectedWeek,
    }),
    [mondayOfSelectedWeek],
  );

  const { shareArticles, refetch: refetchShareArticles } =
    useShareArticles(shareArticleFilters);

  const { offerGroupsCount, offerGroups } = useOfferGroups();

  const currentOfferGroup = offerGroups?.find(
    (og) => og.id === selectedOfferGroup,
  );

  const otherOfferGroups = useMemo(() => {
    if (!selectedOfferGroup || !offerGroups) return [];
    return offerGroups.filter((og) => og.id !== selectedOfferGroup);
  }, [selectedOfferGroup, offerGroups]);

  const offersListParams = useMemo<CommissioningOffersListParams>(
    () => ({
      year: selectedYear,
      delivery_week: selectedWeek,
      offer_group: selectedOfferGroup!,
    }),
    [selectedYear, selectedWeek, selectedOfferGroup],
  );

  // ``isFetching`` (not ``isLoading``) so the grid overlay shows on
  // every refetch — with the global ``staleTime: 0`` a revisited
  // year/week/offer-group key has ``isLoading === false``.
  const { data: offersData, isFetching } = useCommissioningOffersList(
    offersListParams,
    {
      query: { enabled: !!selectedOfferGroup },
    },
  );

  // Derive table rows directly from the query result. No local mirror —
  // the table is read-only via permissions below; any "data change" path
  // goes through invalidateData() which refetches.
  const data = useMemo<TableRecord[]>(
    () => (offersData ?? []) as unknown as TableRecord[],
    [offersData],
  );

  const invalidateData = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: getCommissioningOffersListQueryKey(offersListParams),
    });
  }, [queryClient, offersListParams]);
  const { onSaveSuccess, onDeleteSuccess } =
    useInvalidateAfterTableMutation(invalidateData);

  // `offer_group` is required by the type; we placeholder `""` when not
  // picked and rely on `enabled: !!selectedOfferGroup` below to avoid
  // firing the request. (Previously this used `String(selectedOfferGroup)`
  // which would serialize `null` to the string "null" — caught by the
  // listParams audit.)
  const sendingStatusParams =
    useMemo<CommissioningOfferSendingStatusListParams>(
      () => ({
        year: selectedYear,
        delivery_week: selectedWeek,
        offer_group: selectedOfferGroup ?? "",
      }),
      [selectedYear, selectedWeek, selectedOfferGroup],
    );

  // ``isFetching`` for the same reason as the offers list above: this
  // table is the post-send verification surface, so a refetch must
  // show a spinner instead of stale sent/unsent markers.
  const { data: sendingStatusData, isFetching: statusLoading } =
    useCommissioningOfferSendingStatusList(sendingStatusParams, {
      query: {
        enabled: !!selectedOfferGroup,
      },
    });

  const sendingStatus = useMemo(
    () => (sendingStatusData as unknown as Record<string, unknown>[]) ?? [],
    [sendingStatusData],
  );

  const invalidateSendingStatus = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey:
        getCommissioningOfferSendingStatusListQueryKey(sendingStatusParams),
    });
  }, [queryClient, sendingStatusParams]);

  const resellersForPdf = useMemo(() => {
    if (!usePersonalizedOffers || !sendingStatus || sendingStatus.length === 0)
      return undefined;
    return sendingStatus.map((s) => ({
      reseller_name: String(s.name ?? ""),
      reseller_address: String(s.address ?? ""),
      reseller_zip: String(s.zip_code ?? ""),
      reseller_city: String(s.city ?? ""),
      // reseller_country: s.country ? String(s.country) : undefined,
      reseller_uid: s.uid ? String(s.uid) : undefined,
    }));
  }, [usePersonalizedOffers, sendingStatus]);

  const allFinalized = useMemo(() => {
    if (data.length === 0) return false;
    return data.every((record) => record.is_finalized === true);
  }, [data]);

  return {
    shareArticleFilters,
    shareArticles,
    refetchShareArticles,
    offerGroupsCount,
    currentOfferGroup,
    otherOfferGroups,
    data,
    isFetching,
    invalidateData,
    onSaveSuccess,
    onDeleteSuccess,
    sendingStatus,
    statusLoading,
    invalidateSendingStatus,
    resellersForPdf,
    allFinalized,
  };
}
