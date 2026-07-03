/**
 * Offers page. Deliberately thin: selector/modal/selection state and
 * layout live here; the queries + derived flags are ``useOffersData``,
 * every column shape (incl. the price-tier group) is
 * ``useOffersColumns``, and the larger UI sections are components
 * under ``./components/``.
 */

import { ExclamationCircleOutlined, SendOutlined } from "@ant-design/icons";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import { Button, Checkbox, Flex } from "antd";
import dayjs from "dayjs";
import { lazy, Suspense, useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import {
  commissioningBulkSendOffersViaEmailCreate,
  commissioningCreateOffersCreate,
  commissioningOffersCreate,
  commissioningOffersDestroy,
  commissioningOffersPartialUpdate,
} from "@shared/api/generated/commissioning/commissioning";
import type { Offer } from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
import { JobProgressDrawer } from "@shared/ui/JobProgressDrawer";
import { SendOffersModal } from '@features/commissioning/modals';
// OfferPDFGenerator statically imports @react-pdf/renderer (it uses
// ``PDFDownloadLink`` for the offer-pdf download). Lazy-loading
// keeps the ~484 KB gzip PDF chunk out of Offers.tsx's eager bundle.
// The component only ever renders when an offer group is selected
// AND all offers are finalized — so the chunk loads on first
// "ready for download" state, not on page open.
const OfferPDFGenerator = lazy(
  () => import("@features/commissioning/pdfs/forResellers/OfferPDFGenerator"),
);
import { WeekSelector } from '@shared/selectors';
import { OfferGroupSelector } from '@features/commissioning/selectors';
import {
  EditableTable,
  gatedByPermission,
  wrapApiFunctions,
} from "@shared/tables";
import type {
  ApiFunctions,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { ExplainerText, PastWarningMessage, ToolTipIcon } from '@shared/ui';
import { AddShareArticleEntry } from '@features/commissioning/components';
import { useTableRowSelection, useTenantSettingToggle } from '@hooks/index';
import { useOffersColumns, useOffersData } from '@features/commissioning/hooks';
import { isWeekInPast, notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";
import OfferSendingStatusTable from "@features/commissioning/components/OfferSendingStatusTable";
import OffersBulkActions from "@features/commissioning/components/OffersBulkActions";

const currentYear = dayjs().year();
const nextWeek = dayjs().isoWeek();

export default function Offers() {
  const { isOffice } = useRoles();
  const [selectedYear, setSelectedYear] = useState(currentYear);
  const [selectedWeek, setSelectedWeek] = useState(nextWeek);
  const [selectedOfferGroup, setSelectedOfferGroup] = useState<string | null>(
    null,
  );
  const isPast = useMemo(
    () => isWeekInPast(selectedYear, selectedWeek),
    [selectedYear, selectedWeek],
  );
  const permissions = useMemo(
    () => ({
      ...gatedByPermission(isOffice && !isPast),
      canDeleteRecord: (record: TableRecord) =>
        !((record.amount_ordered as number) > 0),
    }),
    [isOffice, isPast],
  );
  const [isSendOffersModalOpen, setIsSendOffersModalOpen] = useState(false);
  // ID of the active Huey-backed offer-send job; ``null`` when no
  // send is in flight. Drives the JobProgressDrawer below.
  const [activeJobId, setActiveJobId] = useState<string | null>(null);

  const { t } = useTranslation();

  const { value: pricesPerPU, onChange: handlePricesPerPUChange } =
    useTenantSettingToggle("offer_prices_are_per_pu", false);

  const { value: usePersonalizedOffers, onChange: handlePersonalizedOffersChange } =
    useTenantSettingToggle("use_personalized_offers", true);

  const {
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
  } = useOffersData({
    selectedYear,
    selectedWeek,
    selectedOfferGroup,
    usePersonalizedOffers,
  });

  const { columns } = useOffersColumns({
    shareArticleFilters,
    shareArticles,
    currentOfferGroup,
    selectedOfferGroup,
  });

  const {
    selectedRowKeys,
    onSelectedRowsChange: handleRowSelectionChange,
    rowSelection: rowSelectionConfig,
    clearSelection,
  } = useTableRowSelection(
    (record: TableRecord) => record.key === -1 || isPast,
  );

  // No ``list`` here: the page owns the data (``useOffersData`` →
  // ``initialData``), so the table must never fetch it itself.
  const apiFunctions = useMemo<ApiFunctions>(
    () =>
      wrapApiFunctions<Offer & TableRecord>({
        create: (payload) => commissioningOffersCreate(payload),
        update: (id, payload) => commissioningOffersPartialUpdate(id, payload),
        delete: (id) => commissioningOffersDestroy(id),
      }),
    [],
  );

  const customSave = useCallback(
    (transformedData: Record<string, unknown>) => {
      return {
        ...transformedData,
        year: selectedYear,
        delivery_week: selectedWeek,
        offer_group: selectedOfferGroup,
      };
    },
    [selectedYear, selectedWeek, selectedOfferGroup],
  );

  const customEdit = useCallback(
    (
      record: TableRecord,
      form: { setFieldsValue: (values: Record<string, unknown>) => void },
    ) => {
      if (record.key === -1) {
        const defaultValues = { size: "M" };
        form.setFieldsValue(defaultValues);
        return { ...record, ...defaultValues };
      }
      return record;
    },
    [],
  );

  const handleSendOffers = async () => {
    if (!selectedOfferGroup) {
      alert(t("commissioning.please_select_offer_group"));
      return;
    }
    setIsSendOffersModalOpen(true);
  };

  const handleSendOffersToResellers = useCallback(
    async (resellerIds: string[]) => {
      if (!selectedOfferGroup) return;

      // The bulk-send endpoint now enqueues a Huey job and returns
      // 202 with ``{job_id, kind, status}``. Open the progress
      // drawer; ``useJob`` (inside the drawer) polls until the job
      // lands in a terminal state, at which point we refresh the
      // sending-status table so the office sees the freshly-stamped
      // OfferSending rows.
      const resp = (await commissioningBulkSendOffersViaEmailCreate({
        reseller_ids: resellerIds,
        year: selectedYear,
        delivery_week: selectedWeek,
        offer_group: selectedOfferGroup,
      })) as unknown as { job_id?: string };

      if (resp?.job_id) {
        setActiveJobId(resp.job_id);
      }
    },
    [selectedOfferGroup, selectedYear, selectedWeek],
  );

  const handleCreateOffer = async () => {
    // Offer creation is intentionally for ALL offer groups: ``CreateOffersView``
    // generates offers for every group and ignores any ``offer_group`` in the
    // payload, so we neither require a selection nor send one. The group
    // selector below only scopes the table/PDF/send view, not creation.
    try {
      const response = await commissioningCreateOffersCreate({
        year: selectedYear,
        delivery_week: selectedWeek,
      } as never);

      const responseData = response as unknown as Record<string, unknown>;
      if (responseData.success) {
        notify.success(
          t("commissioning.offers_created", {
            created: responseData.created_count,
          }),
        );
        invalidateData();
      } else {
        // Map the backend's English sentinel strings to translated
        // keys so the office sees a localized notification. Unknown
        // messages still flow through verbatim (covers ad-hoc
        // error strings the service may add later without a frontend
        // refresh). See ``OfferService.create_offers`` and
        // ``reseller_views.create_offers``.
        const rawMessage = responseData.message as string | undefined;
        const localized =
          rawMessage === "No offer groups found"
            ? t("commissioning.no_offer_groups_found")
            : rawMessage === "No offers created"
              ? t("commissioning.no_offers_created")
              : rawMessage || t("commissioning.no_offers_created");
        notify.info(localized);
      }
    } catch (error) {
      notify.error(
        getErrorMessage(error, t("commissioning.failed_to_create_offers")),
      );
    }
  };

  if (offerGroupsCount === 0) {
    return (
      <div>
        <h1>{t("commissioning.offers")}</h1>
        <div
          className="past-warning-message"
          style={{ width: "60em", paddingLeft: "1em" }}
        >
          {" "}
          <ExclamationCircleOutlined style={{ color: "#ffa800" }} />
          <p>
            {t("commissioning.no_offer_groups_message")}{" "}
            <Link
              to="/commissioning/list-offer-groups"
              style={{
                color: "#0066cc",
                textDecoration: "underline",
              }}
            >
              {t("commissioning.manage_offer_groups")}
            </Link>
          </p>
        </div>
      </div>
    );
  }

  return (
    <div>
      <h1>{t("commissioning.offers")}</h1>
      <WeekSelector
        selectedYear={selectedYear}
        setSelectedYear={setSelectedYear}
        selectedWeek={selectedWeek}
        setSelectedWeek={(v) => v !== null && setSelectedWeek(v)}
      />
      <div className="section-divider">
        <Button
          icon={<AutoAwesomeIcon />}
          onClick={handleCreateOffer}
          disabled={isPast}
          type="primary"
        >
          {t("commissioning.create_offer")}
        </Button>
        <ToolTipIcon title={t("tooltip.offer_creation_button")} />
      </div>
      {/* The group selector + reseller list sit BELOW the create button on
          purpose: creation is for all groups, so these only scope the table /
          PDF / send view (and individual-offer adds) below. */}
      <OfferGroupSelector
        selectedOfferGroup={selectedOfferGroup}
        setSelectedOfferGroup={setSelectedOfferGroup}
        onOfferGroupChange={setSelectedOfferGroup}
        include_null_option={true}
      />
      <div style={{ marginTop: "1em" }}>
        <strong>{t("commissioning.reseller_in_this_offer_group")}</strong>{" "}
        <br />
        {currentOfferGroup?.reseller_names}
      </div>
      {!isPast && (
        <div className="bulk-actions-header">
          <strong>{t("commissioning.for_selected")}</strong>
        </div>
      )}

      <OffersBulkActions
        selectedRowKeys={selectedRowKeys}
        onClearSelection={clearSelection}
        onInvalidate={invalidateData}
        otherOfferGroups={otherOfferGroups}
        selectedYear={selectedYear}
        selectedWeek={selectedWeek}
      />
      {isPast && (
        <PastWarningMessage>{t("table.past_week_readonly")}</PastWarningMessage>
      )}
      <EditableTable
        key={`${selectedYear}-${selectedWeek}`}
        columns={columns}
        apiFunctions={apiFunctions}
        focusIndex="share_article_name"
        initialData={data}
        loading={isFetching}
        customSave={customSave}
        customEdit={customEdit}
        onSaveSuccess={onSaveSuccess}
        onDeleteSuccess={onDeleteSuccess}
        deleteContext={{
          selectedYear,
          selectedWeek,
        }}
        permissions={permissions}
        rowSelection={rowSelectionConfig}
        onSelectedRowsChange={handleRowSelectionChange}
        selectedRowKeys={selectedRowKeys}
      />
      <SendOffersModal
        open={isSendOffersModalOpen}
        onClose={() => setIsSendOffersModalOpen(false)}
        resellers={sendingStatus.map((s) => ({
          id: String(s.id),
          name: String(s.name),
          sent: Boolean(s.sent),
          sent_at: s.sent_at ? String(s.sent_at) : null,
        }))}
        onSend={handleSendOffersToResellers}
        year={selectedYear}
        week={selectedWeek}
        offerGroupName={currentOfferGroup?.name ?? undefined}
      />

      <JobProgressDrawer
        jobId={activeJobId}
        onClose={() => {
          // Closing the drawer refreshes the sending-status table —
          // when the job is done, OfferSending rows just got written
          // and the office expects to see the "Sent ✓" markers
          // immediately. Cheap if no rows changed; covers both the
          // happy and failure paths.
          invalidateSendingStatus();
          setActiveJobId(null);
        }}
        title={t("commissioning.send_offers")}
      />
      <AddShareArticleEntry
        disabled={isPast}
        onSuccess={() => refetchShareArticles()}
      />

      <div
        className="flex-col gap-8"
        style={{
          margin: "16px 0",
        }}
      >
        <Flex align="center" gap="8px" component="label">
          <Checkbox
            checked={pricesPerPU}
            onChange={(e) => handlePricesPerPUChange(e.target.checked)}
          />
          <span>{t("settings.reseller.offer_prices_are_per_pu")}</span>
        </Flex>
        <Flex align="center" gap="8px" component="label">
          <Checkbox
            checked={usePersonalizedOffers}
            onChange={(e) => handlePersonalizedOffersChange(e.target.checked)}
          />
          <span>{t("commissioning.use_personalized_offers")}</span>
          <ToolTipIcon title={t("tooltip.use_personalized_offers")} />
        </Flex>
      </div>
      <div style={{ marginBottom: 16, marginTop: 16 }}>
        {selectedOfferGroup && data.length > 0 && allFinalized && (
          <>
            <Suspense fallback={<Button loading size="middle" type="primary" />}>
              <OfferPDFGenerator
                year={selectedYear}
                delivery_week={selectedWeek}
                offerGroupId={selectedOfferGroup}
                buttonText={t("commissioning.download_offers_pdf")}
                buttonSize="middle"
                resellerInfo={null}
                resellers={resellersForPdf}
                pricesPerPU={pricesPerPU}
              />
            </Suspense>
            <ToolTipIcon title={t("tooltip.download_offers_pdf")} />
          </>
        )}
      </div>
      <div style={{ marginBottom: 16, marginTop: 16 }}>
        <Button
          icon={<SendOutlined />}
          onClick={handleSendOffers}
          disabled={isPast || data.length === 0 || !allFinalized}
          className="download-pdf-button"
          type="primary"
        >
          {t("commissioning.send_offers_via_email")}
        </Button>
        <ToolTipIcon title={t("tooltip.send_offers_button")} />
      </div>
      <OfferSendingStatusTable
        sendingStatus={sendingStatus}
        loading={statusLoading}
      />
      <ExplainerText title={t("common.info")}>
        {t("explainers.offers")}
      </ExplainerText>
    </div>
  );
}
