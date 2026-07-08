import {
  ClockCircleOutlined,
  CloseCircleOutlined,
  MailOutlined,
  StopOutlined,
} from "@ant-design/icons";
import NewSubscriptionModal from "@features/abos/modals/NewSubscriptionModal";
import {
  CancelMembershipModal,
  CoopSharesModal,
  MemberCoopSharesModal,
  MemberDeliveryEditModal,
} from "@features/members/modals";
import SuccessModal from "@shared/modals/SuccessModal";
import { useLogoShape, useTenant } from "@hooks/index";
import {
  getCommissioningAbosListQueryKey,
  getCommissioningMembersRetrieveQueryKey,
  getCommissioningShareDeliveryListQueryKey,
  useCommissioningAbosList,
  useCommissioningMembersRetrieve,
  useCommissioningShareDeliveryExceptionGapsList,
  useCommissioningShareDeliveryList,
  useCommissioningShareDeliveryToggleOptinCreate,
} from "@shared/api/generated/commissioning/commissioning";
import { notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";
import { getWeekdayChoices } from "@shared/utils/weekdayChoices";
import type { ShareDelivery } from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
import { useQueryClient } from "@tanstack/react-query";
import {
  Avatar,
  Button,
  Card,
  Col,
  Result,
  Row,
  Space,
  Spin,
  Typography,
} from "antd";
import dayjs from "dayjs";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";
import ActiveSubscriptionsCard from "../components/ActiveSubscriptionsCard";
import CoopSharesCard from "../components/CoopSharesCard";
import CurrentWeekDeliveryCard from "../components/CurrentWeekDeliveryCard";
import DeliveryStationDaysCard from "../components/DeliveryStationDaysCard";
import MemberConsentsCard from "../components/MemberConsentsCard";
import PaymentsCard from "../components/PaymentsCard";
import UpcomingDeliveriesCard from "../components/UpcomingDeliveriesCard";

const { Text } = Typography;

const MemberDetail = () => {
  const { id } = useParams<{ id: string }>();
  const { t } = useTranslation();
  const { logoUrl, displayLogoUrl, tenantName } = useTenant();
  const { isMemberOnly } = useRoles();
  const queryClient = useQueryClient();
  const [deliveryModalVisible, setDeliveryModalVisible] = useState(false);
  const [newSubscriptionModalVisible, setNewSubscriptionModalVisible] =
    useState(false);
  const [coopSharesModalVisible, setCoopSharesModalVisible] = useState(false);
  const [cancelMembershipVisible, setCancelMembershipVisible] = useState(false);
  const [subscribeSuccessOpen, setSubscribeSuccessOpen] = useState(false);
  const [selectedDelivery, setSelectedDelivery] =
    useState<ShareDelivery | null>(null);
  const { logoShape, logoAspectRatio } = useLogoShape(displayLogoUrl);

  const currentWeek = dayjs().isoWeek();
  const currentYear = dayjs().year();

  const { data: member, isLoading: memberLoading } =
    useCommissioningMembersRetrieve(id!, {
      query: { enabled: !!id },
    });

  const { data: shareDeliveriesData } = useCommissioningShareDeliveryList(
    { member: id, year: currentYear },
    { query: { enabled: !!id } },
  );

  // Also fetch NEXT year: a subscription that starts in the next calendar year
  // has its deliveries (and jokers) there, so a current-year-only query would
  // hide all of a not-yet-started membership's future deliveries.
  const { data: nextYearDeliveriesData } = useCommissioningShareDeliveryList(
    { member: id, year: currentYear + 1 },
    { query: { enabled: !!id } },
  );

  // On-off opt-in toggle (folded into the deliveries card — no separate card).
  // The deadline / lock state lives on each ShareDelivery row; the dedicated
  // endpoint stamps the audit fields + re-runs billing, then we refetch both
  // year queries (no-arg key → prefix match).
  const {
    mutate: toggleOptin,
    isPending: isTogglingOptin,
    variables: togglingOptinVars,
  } = useCommissioningShareDeliveryToggleOptinCreate({
    mutation: {
      onSuccess: () => {
        queryClient.invalidateQueries({
          queryKey: getCommissioningShareDeliveryListQueryKey(),
        });
      },
      onError: (err) =>
        notify.error(getErrorMessage(err, t("members.optin_toggle_failed"))),
    },
  });
  const handleToggleOptin = useCallback(
    (delivery: ShareDelivery, optIn: boolean) =>
      toggleOptin({ id: String(delivery.id), data: { opt_in: optIn } }),
    [toggleOptin],
  );

  const { data: subscriptions } = useCommissioningAbosList(
    { member: id, is_trial: false },
    { query: { enabled: !!id } },
  );

  // Weeks the member's subscriptions WOULD deliver but don't, because a
  // delivery exception (Lieferpause) removed the ShareDelivery — there is no
  // ShareDelivery row for these, so the card can't derive them. One call covers
  // ``year`` + ``year+1`` (same window as the two delivery fetches above).
  const { data: exceptionGapsData } =
    useCommissioningShareDeliveryExceptionGapsList(
      { member: id ?? "", year: currentYear },
      { query: { enabled: !!id } },
    );
  const exceptionGaps = useMemo(
    () => exceptionGapsData ?? [],
    [exceptionGapsData],
  );

  // Memoize the empty-fallback so downstream memos depending on
  // `shareDeliveries` don't invalidate on every render until data lands.
  const shareDeliveries = useMemo(
    () => [...(shareDeliveriesData ?? []), ...(nextYearDeliveriesData ?? [])],
    [shareDeliveriesData, nextYearDeliveriesData],
  );

  // Confirmed subscriptions whose term hasn't ended — INCLUDING ones that
  // haven't started yet. Their FUTURE deliveries / payments / jokers must show
  // on the member's detail; the old `valid_from <= today` gate hid every
  // not-yet-started membership (and everything derived from it). ActiveSubscriptions
  // Card recomputes its own "currently active" set, so this rename doesn't affect it.
  const confirmedSubscriptions = useMemo(() => {
    if (!subscriptions?.length) return [];
    const today = dayjs().format("YYYY-MM-DD");
    return subscriptions.filter(
      (sub) =>
        sub.admin_confirmed && (!sub.valid_until || sub.valid_until >= today),
    );
  }, [subscriptions]);

  const confirmedSubscriptionIds = useMemo(
    () => new Set(confirmedSubscriptions.map((sub) => sub.id)),
    [confirmedSubscriptions],
  );

  const confirmedDeliveries = useMemo(
    () =>
      shareDeliveries.filter(
        (d) => d.subscription && confirmedSubscriptionIds.has(d.subscription),
      ),
    [shareDeliveries, confirmedSubscriptionIds],
  );

  const weekdayChoices = useMemo(() => getWeekdayChoices(t), [t]);

  const handleDeliveryEdit = (delivery: ShareDelivery) => {
    setSelectedDelivery(delivery);
    setDeliveryModalVisible(true);
  };

  const handleDeliverySuccess = () => {
    setDeliveryModalVisible(false);
    setSelectedDelivery(null);
    queryClient.invalidateQueries({
      queryKey: getCommissioningShareDeliveryListQueryKey({
        member: id,
        year: currentYear,
      }),
    });
  };

  // With the app-wide staleTime:0 the first (uncached) navigation renders
  // while the retrieve is in flight; show a spinner until it settles so the
  // "not found" screen is reserved for a genuine 404 (not a loading flash).
  if (memberLoading) {
    return (
      <div className="flex-center" style={{ minHeight: "60vh" }}>
        <Spin size="large" />
      </div>
    );
  }

  if (!member) {
    return (
      <div
        className="flex-center"
        style={{
          minHeight: "60vh",
          flexDirection: "column",
          gap: "16px",
        }}
      >
        <Text type="secondary" style={{ fontSize: "18px" }}>
          {t("members.member_not_found")}
        </Text>
        <Button type="primary" onClick={() => window.history.back()}>
          {t("common.go_back")}
        </Button>
      </div>
    );
  }

  // Pending / rejected gate — shown ONLY to members viewing their own
  // profile (``isMemberOnly``). Office / staff viewers still see the
  // full profile because they're the ones reviewing the application.
  //
  // We don't actually leak any sensitive data by skipping this gate
  // for office viewers — the security audit confirmed every endpoint
  // is own-data-scoped — but the member-facing UX is the point: a
  // half-rendered dashboard with empty cards reads as broken; a clear
  // "your application is being reviewed" page reads as expected.
  //
  // Logo above the gate's icon — visual continuity with the rest of
  // the tenant's branding so the page doesn't look like a generic
  // error screen. Falls back gracefully when the tenant has no logo
  // configured (the <img> simply doesn't render).
  const gateLogo = logoUrl ? (
    <div
      style={{
        display: "flex",
        justifyContent: "center",
        marginBottom: 16,
      }}
    >
      <img
        src={logoUrl}
        alt={tenantName ?? t("common.logo")}
        style={{
          maxHeight: 80,
          maxWidth: 200,
          objectFit: "contain",
        }}
      />
    </div>
  ) : null;

  // Bilingual helper for the gate copy: render the DE text as the
  // primary line and a muted EN line below. Since unconfirmed
  // applicants may be browsing in either language (and the gate is
  // their first impression), showing both removes the guesswork
  // without forcing them to change the app language first.
  //
  // ``t(key, { lng: 'en' })`` looks up a specific language for one
  // call without touching the global i18next state — so the rest of
  // the page (when it becomes visible after confirmation) still
  // honours whatever language they've picked.
  const bilingual = (deKey: string, enFallback: string) => (
    <>
      <div>{t(deKey, { lng: "de" })}</div>
      <div
        style={{
          marginTop: 4,
          fontSize: "0.85em",
          color: "var(--color-text-muted)",
          fontStyle: "italic",
        }}
      >
        {t(deKey, { lng: "en", defaultValue: enFallback })}
      </div>
    </>
  );

  if (isMemberOnly && member.admin_rejected_at) {
    return (
      <div style={{ padding: "24px", maxWidth: 720, margin: "0 auto" }}>
        {gateLogo}
        <Result
          status="error"
          icon={<CloseCircleOutlined />}
          title={bilingual(
            "members.application_rejected_title",
            "Your application was not accepted.",
          )}
          subTitle={
            member.admin_rejection_reason ? (
              <>
                {t("members.reject_reason_label", { lng: "de" })}:{" "}
                {member.admin_rejection_reason}
                <div
                  style={{
                    marginTop: 4,
                    fontSize: "0.85em",
                    color: "var(--color-text-muted)",
                    fontStyle: "italic",
                  }}
                >
                  {t("members.reject_reason_label", {
                    lng: "en",
                    defaultValue: "Reason",
                  })}
                  : {member.admin_rejection_reason}
                </div>
              </>
            ) : (
              bilingual(
                "members.application_rejected_subtitle",
                "The office decided not to accept your application at this time. Please contact us if you have questions.",
              )
            )
          }
        />
      </div>
    );
  }

  if (isMemberOnly && !member.admin_confirmed) {
    return (
      <div style={{ padding: "24px", maxWidth: 720, margin: "0 auto" }}>
        {gateLogo}
        <Result
          status="info"
          icon={<ClockCircleOutlined />}
          title={bilingual(
            "members.application_pending_title",
            "Your application is being reviewed.",
          )}
          subTitle={bilingual(
            "members.application_pending_subtitle",
            "Thanks for signing up. The office hasn't confirmed your membership yet — once they do, your portal will unlock with your subscriptions, deliveries, and payments. We'll email you the moment it's done.",
          )}
        />
      </div>
    );
  }

  const sizeLogo = 120;

  return (
    <div style={{ padding: "24px", maxWidth: "1400px", margin: "0 auto" }}>
      {/* Header Section */}
      <Card
        style={{
          marginBottom: "24px",
          background: "var(--gradient-primary)",
          color: "var(--color-bg-base)",
        }}
        styles={{ body: { padding: "16px" } }}
      >
        <Row align="middle" gutter={24}>
          <Col>
            {displayLogoUrl &&
              (logoShape === "rectangle-wide" ||
              logoShape === "rectangle-tall" ? (
              <div
                style={{
                  width:
                    logoShape === "rectangle-wide"
                      ? `${sizeLogo * logoAspectRatio}px`
                      : `${sizeLogo}px`,
                  height:
                    logoShape === "rectangle-wide"
                      ? `${sizeLogo}px`
                      : `${sizeLogo / logoAspectRatio}px`,

                  borderRadius: "8px",
                  backgroundColor: "var(--color-bg-base)",
                  padding: "8px",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  overflow: "hidden",
                }}
              >
                <img
                  src={displayLogoUrl}
                  alt={tenantName ?? t("common.logo")}
                  style={{
                    width: "100%",
                    height: "100%",
                    objectFit: "contain",
                  }}
                />
              </div>
            ) : (
              <Avatar
                size={64}
                src={displayLogoUrl}
                shape="circle"
                style={{
                  backgroundColor: "var(--color-bg-base)",
                  padding: "8px",
                }}
              />
            ))}
          </Col>
          <Col flex="auto">
            <h1 style={{ color: "var(--color-bg-base)", marginBottom: "8px" }}>
              {member.first_name} {member.last_name}
            </h1>
            <Space size="large">
              <Text style={{ color: "rgba(255,255,255,0.9)" }}>
                <MailOutlined /> {member.email}
              </Text>
            </Space>
          </Col>
        </Row>
      </Card>

      <Row gutter={[24, 24]}>
        {/* Left column — abos & deliveries: active abos (with "+ new"),
            current deliveries, add new deliveries (opt-in), upcoming
            deliveries, joker. */}
        <Col xs={24} lg={12}>
          <ActiveSubscriptionsCard
            subscriptions={subscriptions ?? []}
            onNewSubscription={() => setNewSubscriptionModalVisible(true)}
            canAdd={!member.cancelled_at}
          />
          <CurrentWeekDeliveryCard
            shareDeliveries={confirmedDeliveries}
            currentWeek={currentWeek}
            currentYear={currentYear}
          />
          <UpcomingDeliveriesCard
            shareDeliveries={confirmedDeliveries}
            exceptionGaps={exceptionGaps}
            currentWeek={currentWeek}
            currentYear={currentYear}
            weekdayChoices={weekdayChoices}
            onEditDelivery={handleDeliveryEdit}
            onToggleOptin={handleToggleOptin}
            togglingOptinId={
              isTogglingOptin ? (togglingOptinVars?.id ?? null) : null
            }
          />
        </Col>
        {/* Right column — membership, money, legal: My Membership (equity +
            entry/exit dates), payments, consents. */}
        <Col xs={24} lg={12}>
          <CoopSharesCard
            member={member}
            onManage={() => setCoopSharesModalVisible(true)}
          />
          <DeliveryStationDaysCard memberId={id!} />
          <PaymentsCard memberId={id!} />
          <MemberConsentsCard memberId={id!} />

          {/* Member self-service membership cancellation. Only their own,
              confirmed, not-yet-cancelled membership. The endpoint refuses
              while active subscriptions remain (the office can force-cancel
              from the members table instead). */}
          {isMemberOnly && member.admin_confirmed && !member.cancelled_at && (
            <Card style={{ marginTop: 16 }}>
              <Text type="secondary">
                {t("members.cancel_membership_self_hint")}
              </Text>
              <div style={{ marginTop: 12 }}>
                <Button
                  danger
                  icon={<StopOutlined />}
                  onClick={() => setCancelMembershipVisible(true)}
                >
                  {t("members.cancel_membership_self_button")}
                </Button>
              </div>
            </Card>
          )}
        </Col>
      </Row>

      {/* New Subscription Modal */}
      <NewSubscriptionModal
        visible={newSubscriptionModalVisible}
        memberId={id!}
        subscriptions={subscriptions ?? []}
        onCancel={() => setNewSubscriptionModalVisible(false)}
        onSuccess={() => {
          setNewSubscriptionModalVisible(false);
          setSubscribeSuccessOpen(true);
          queryClient.invalidateQueries({
            queryKey: getCommissioningAbosListQueryKey({
              member: id,
              is_trial: false,
            }),
          });
          queryClient.invalidateQueries({
            queryKey: getCommissioningShareDeliveryListQueryKey({
              member: id,
              year: currentYear,
            }),
          });
          queryClient.invalidateQueries({
            queryKey: getCommissioningShareDeliveryListQueryKey({
              member: id,
              year: currentYear + 1,
            }),
          });
        }}
      />

      {/* "Thank you" confirmation after a subscription is created. */}
      <SuccessModal
        open={subscribeSuccessOpen}
        onClose={() => setSubscribeSuccessOpen(false)}
        subtitle={t("members.subscription_created_success")}
      />

      {/* Delivery Edit Modal */}
      <MemberDeliveryEditModal
        visible={deliveryModalVisible}
        onCancel={() => {
          setDeliveryModalVisible(false);
          setSelectedDelivery(null);
        }}
        onSuccess={handleDeliverySuccess}
        delivery={selectedDelivery}
      />

      {/* Coop-shares ("Genossenschaftsanteile") view / subscribe modal.
          Members self-subscribe (pending office confirmation) via the slim
          MemberCoopSharesModal; office/staff get the full editable modal. */}
      {isMemberOnly ? (
        <MemberCoopSharesModal
          isOpen={coopSharesModalVisible}
          memberId={id!}
          memberCancelledEffectiveAt={member.cancelled_effective_at ?? null}
          onClose={() => setCoopSharesModalVisible(false)}
        />
      ) : (
        <CoopSharesModal
          isOpen={coopSharesModalVisible}
          memberId={id!}
          memberName={`${member.first_name ?? ""} ${member.last_name ?? ""}`.trim()}
          isTrial={member.is_trial ?? false}
          adminConfirmed={member.admin_confirmed ?? false}
          memberCancelledEffectiveAt={member.cancelled_effective_at ?? null}
          onClose={() => {
            setCoopSharesModalVisible(false);
            // Refresh the member detail so the card's coop_shares_total reflects
            // any shares just subscribed/edited in the modal.
            queryClient.invalidateQueries({
              queryKey: getCommissioningMembersRetrieveQueryKey(id),
            });
          }}
        />
      )}

      <CancelMembershipModal
        isOpen={cancelMembershipVisible}
        self
        onClose={() => setCancelMembershipVisible(false)}
        onCancelled={() =>
          queryClient.invalidateQueries({
            queryKey: getCommissioningMembersRetrieveQueryKey(id),
          })
        }
      />
    </div>
  );
};

export default MemberDetail;
