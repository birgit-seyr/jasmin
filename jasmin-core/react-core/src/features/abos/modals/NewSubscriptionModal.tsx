import { ArrowLeftOutlined, CheckCircleFilled } from "@ant-design/icons";
import DOMPurify from "dompurify";
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  Col,
  DatePicker,
  Flex,
  Form,
  InputNumber,
  Modal,
  Row,
  Select,
  Space,
  Tag,
  Typography,
} from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { type FC, useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  commissioningAbosCreate,
  commissioningMySubscriptionsSubscribeCreate,
} from "@shared/api/generated/commissioning/commissioning";
import type { Subscription } from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
import { ModalCancelSaveFooter } from "@shared/modals/shared";
import {
  useAllShareTypeVariations,
  useCurrency,
  useDateFormat,
  useDeliveryStationDays,
  usePaymentCycles,
  useShareTypes,
  useShareTypeVariationSizeOptions,
  useSubscriptionTerm,
  useTenant,
} from "@hooks/index";
import type { ShareTypeVariationOption } from "@hooks/useAllShareTypeVariations";
import {
  CAPACITY_SHARE_OPTIONS,
  capacityWindowParams,
  stationDayTermCapacity,
} from "@features/abos/utils/stationCapacity";
import { DeliveryStationMap } from "@shared/ui";
import type { DeliveryStationMapMarker } from "@shared/ui";
import ToolTipIcon from "@shared/ui/ToolTipIcon";
import { notify } from "@shared/utils";
import { getErrorCode, getErrorMessage } from "@shared/utils/apiError";

const { Text, Title, Paragraph } = Typography;

// Office descriptions are rich text (HTML) and often glue words together with
// non-breaking spaces (the &nbsp; entity OR the U+00A0 char). Sanitise, then
// swap those for normal spaces so the text wraps at word boundaries instead of
// running off as one long line (or being force-broken mid-word).
const cleanDescriptionHtml = (html: string): string =>
  DOMPurify.sanitize(html)
    .replace(/&nbsp;/gi, " ")
    .replace(/\u00a0/g, " ");

interface NewSubscriptionModalProps {
  visible: boolean;
  memberId: string;
  subscriptions?: Subscription[];
  onCancel: () => void;
  onSuccess: () => void;
}

const NewSubscriptionModal: FC<NewSubscriptionModalProps> = ({
  visible,
  memberId,
  subscriptions = [],
  onCancel,
  onSuccess,
}) => {
  const { t } = useTranslation();
  const { currencySymbol } = useCurrency();
  const { dateFormat, formatDate } = useDateFormat();
  const { getShareTypeVariationSizeLabel } = useShareTypeVariationSizeOptions();
  // A member subscribing for THEMSELVES uses the member-scoped endpoint. The
  // price is read-only (derived server-side) UNLESS the tenant allows
  // solidarity pricing, in which case the member may choose it (>= the
  // variation's floor); there's no trial toggle for members either.
  const { isMemberOnly } = useRoles();
  const { getSetting } = useTenant();
  const allowsSolidarity = Boolean(
    getSetting("allows_solidarity_pricing", false),
  );
  const sentenceTrialAbo = getSetting(
    "info_sentence_about_trial_subscriptions",
  );
  // End-of-term rules shared with the abos table (single source of truth).
  const {
    allowsTrial,
    endOfSeason,
    endAfterOneYear,
    computeValidUntil,
    isValidUntilAuto,
    disabledValidFromDate,
    earliestValidFrom,
  } = useSubscriptionTerm();
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);
  // Set when the backend refused a NORMAL create with
  // delivery_station.over_capacity — renders an inline offer to retry the
  // same create as a waiting-list entry (server-authoritative fullness).
  const [waitlistOffer, setWaitlistOffer] = useState(false);
  const [selectedVariation, setSelectedVariation] =
    useState<ShareTypeVariationOption | null>(null);

  // The chosen start date drives the variation PRICE annotation, so the
  // displayed solidarity floor / reference match what the backend enforces (it
  // resolves the time-bound gross-price window at valid_from, not today).
  // Before a date is picked, default to the EARLIEST possible start
  // (now + min_weeks_from_creation_to_start_delivery, per tenant settings) —
  // NOT today. The first sellable delivery is weeks out, so its price window is
  // the one to show on the cards and prefill; today's price may not even apply.
  const validFrom = Form.useWatch("valid_from", form) as Dayjs | undefined;
  const pricingDate = (validFrom ?? earliestValidFrom).format("YYYY-MM-DD");

  const { shareTypes } = useShareTypes({
    active_at_date: dayjs().format("YYYY-MM-DD"),
    include_future: true,
  });
  // Literal-typed alias: the interface-based ``ShareTypeOption`` has no
  // implicit index signature, which the hook's index-signed ``ShareTypeRef``
  // parameter requires — this bridges the two without a cast.
  const shareTypeRefs: { id?: string | null }[] = shareTypes;
  const { shareTypeVariations } = useAllShareTypeVariations(shareTypeRefs, {
    active_at_date: pricingDate,
    include_future: true,
  });
  const { paymentCycles } = usePaymentCycles();

  // The selected variation re-read from the (valid_from-annotated) list, so its
  // active_solidarity_min / active_price reflect the chosen start date — the
  // ``selectedVariation`` state object was annotated at selection time (today).
  const liveVariation = useMemo(
    () =>
      selectedVariation
        ? (shareTypeVariations?.find(
            (v) => v.value === selectedVariation.value,
          ) ?? selectedVariation)
        : null,
    [shareTypeVariations, selectedVariation],
  );

  // Re-prefill the price when the reference for the effective start date
  // changes: ``active_price_per_delivery`` is annotated at ``pricingDate``
  // (the chosen valid_from, or the earliest possible start), so crossing a
  // time-bound gross-price boundary must update the field — otherwise the
  // office would submit the selection-time (earliest-start) price for a later
  // term. Keyed on the price VALUE, not valid_from, so a manual solidarity
  // edit within the SAME price window is preserved.
  useEffect(() => {
    const reference = liveVariation?.active_price_per_delivery;
    if (reference == null) return;
    form.setFieldsValue({ price_per_delivery: Number.parseFloat(reference) });
  }, [liveVariation?.active_price_per_delivery, form]);

  // ── Capacity window ──────────────────────────────────────────────
  // A station's free slots depend on the subscription's term, so the
  // greying tracks the live ``valid_from`` / ``valid_until`` form values.
  // Both fields are date-restricted (Monday / Sunday), so the watched
  // values already sit on ISO-week boundaries.
  const validUntil = Form.useWatch("valid_until", form) as Dayjs | undefined;
  const isTrial = Form.useWatch("is_trial", form) as boolean | undefined;
  const validFromMs = validFrom ? validFrom.valueOf() : null;
  const validUntilMs = validUntil ? validUntil.valueOf() : null;

  // Every ``"<iso-year>-<iso-week>"`` key in the term. Falls back to the
  // start week alone when there's no end date yet, so an open-ended term
  // doesn't grey out a station for one busy week far in the future.
  const periodWeekKeys = useMemo(() => {
    const start = (validFrom ?? dayjs()).startOf("isoWeek");
    const end = validUntil ? validUntil.startOf("isoWeek") : start;
    const keys: string[] = [];
    let cursor = start;
    while (cursor.isSameOrBefore(end, "week") && keys.length < 60) {
      keys.push(`${cursor.isoWeekYear()}-${cursor.isoWeek()}`);
      cursor = cursor.add(1, "week");
    }
    return keys.length ? keys : [`${start.isoWeekYear()}-${start.isoWeek()}`];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [validFromMs, validUntilMs]);

  // ``capacity_by_week`` is only populated when the request carries
  // year + delivery_week + num_weeks. Use the SAME wide fixed window as the
  // Abos table (capacityWindowParams) — one fetch shape everywhere — so every
  // realistic term's week keys are present and the fullness evaluation is
  // always term-relative instead of anchored to whichever week the modal
  // happened to fetch first (the old 1-week today-anchored fetch made the
  // tag and the submitted flag disagree with the chosen term).
  const dsdParams = useMemo(() => {
    const start = (validFrom ?? dayjs()).startOf("isoWeek");
    return {
      active_at_date: start.format("YYYY-MM-DD"),
      ...capacityWindowParams(),
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [validFromMs]);

  const { deliveryStationDays, loading: stationsLoading } =
    useDeliveryStationDays(dsdParams);

  // ── End-of-term ──────────────────────────────────────────────────
  // The picked variation's ``ShareType.delivery_cycle`` drives the
  // trial-span math; resolve it from the loaded share types.
  const variationCycle = useMemo<string | null>(() => {
    if (!selectedVariation) return null;
    const shareType = shareTypes.find(
      (candidate) =>
        String(candidate.value) === String(selectedVariation.share_type),
    );
    return shareType?.delivery_cycle ?? null;
  }, [shareTypes, selectedVariation]);

  // ``valid_until`` is read-only + auto-filled when the tenant config fully
  // determines it (trial duration, season end, or one-year term). Otherwise
  // it's a free Sunday the office types.
  const lockValidUntil = isValidUntilAuto(isTrial === true);

  useEffect(() => {
    if (!lockValidUntil || !validFrom) return;
    const until = computeValidUntil(validFrom, {
      isTrial: isTrial === true,
      cycle: variationCycle,
    });
    form.setFieldsValue({ valid_until: until ?? undefined });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lockValidUntil, validFromMs, isTrial, variationCycle]);

  // Trial end preview for the is_trial helper text.
  const trialEnd = useMemo(
    () =>
      validFrom
        ? computeValidUntil(validFrom, { isTrial: true, cycle: variationCycle })
        : null,
    [validFrom, variationCycle, computeValidUntil],
  );

  // Tiny explainer under the (disabled) valid_until field.
  const validUntilHint = useMemo(() => {
    if (!lockValidUntil) return null;
    if (isTrial) return t("abos.valid_until_trial_hint");
    if (endOfSeason) return t("abos.valid_until_season_hint");
    if (endAfterOneYear) return t("abos.valid_until_year_hint");
    return null;
  }, [lockValidUntil, isTrial, endOfSeason, endAfterOneYear, t]);

  // Group variations by share type for the visual picker (step 1).
  const variationsByType = useMemo(() => {
    const groups: Record<
      string,
      { typeName: string; variations: ShareTypeVariationOption[] }
    > = {};
    for (const variation of shareTypeVariations) {
      const key = variation.share_type;
      if (!groups[key]) {
        groups[key] = {
          typeName: variation.share_type_name ?? "",
          variations: [],
        };
      }
      groups[key].variations.push(variation);
    }
    for (const group of Object.values(groups)) {
      group.variations.sort(
        (a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0),
      );
    }
    return Object.values(groups);
  }, [shareTypeVariations]);

  // Variation ID → total active quantity (drives the "already subscribed" badge).
  const activeQuantityByVariation = useMemo(() => {
    const today = dayjs().format("YYYY-MM-DD");
    const map: Record<string, number> = {};
    for (const sub of subscriptions) {
      if (
        sub.admin_confirmed &&
        sub.valid_from <= today &&
        (!sub.valid_until || sub.valid_until >= today) &&
        sub.share_type_variation
      ) {
        map[sub.share_type_variation] =
          (map[sub.share_type_variation] ?? 0) + (sub.quantity ?? 1);
      }
    }
    return map;
  }, [subscriptions]);

  // Capacity is only DEFINED relative to a term: "full" means some week of
  // [valid_from, valid_until] has no free slot. Until both dates are known we
  // therefore show NO capacity claims at all (the old today-anchored numbers
  // answered a different question than the one that matters). Capacity also
  // only applies to harvest variations — add-on shares (chicken, honey, …)
  // ride along in the base box and never consume a slot, so they never see
  // a full tag or a waitlist offer.
  const termKnown = Boolean(validFrom && validUntil);
  const capacityRelevant = useMemo(() => {
    if (!selectedVariation) return false;
    const shareType = shareTypes.find(
      (candidate) =>
        String(candidate.value) === String(selectedVariation.share_type),
    );
    return CAPACITY_SHARE_OPTIONS.includes(shareType?.share_option ?? "");
  }, [shareTypes, selectedVariation]);
  const showCapacity = termKnown && capacityRelevant;

  // Station options: full station-days stay SELECTABLE — picking one turns
  // the subscription into a waiting-list entry (the office promotes it later
  // via the normal confirm flow). The smaller secondary line shows the
  // tightest term week's free slots as "freie Plätze (free/total)".
  const stationOptions = useMemo(() => {
    return deliveryStationDays.map((dsd) => {
      const { total, minFree, isFull } = showCapacity
        ? stationDayTermCapacity(
            dsd.capacity,
            dsd.capacity_by_week,
            periodWeekKeys,
          )
        : { total: null, minFree: null, isFull: false };
      return {
        value: dsd.value,
        label: dsd.label,
        total,
        free: minFree,
        isFull,
      };
    });
  }, [deliveryStationDays, periodWeekKeys, showCapacity]);

  // Currently-picked station-day (shared with the Select via the same form
  // field), used to highlight the matching map marker.
  const selectedStationDay = Form.useWatch(
    "default_delivery_station_day",
    form,
  ) as string | undefined;

  // Map markers: ONE per delivery station (a station can host several days).
  // Only stations with coordinates appear; the popup lists that station's days
  // as buttons that set the same ``default_delivery_station_day`` field the
  // Select drives. A station is greyed only when EVERY one of its days is full.
  const stationMarkers = useMemo<DeliveryStationMapMarker[]>(() => {
    const capacityByDay = new Map(
      stationOptions.map((opt) => [opt.value, opt]),
    );
    const byStation = new Map<
      string,
      {
        stationId: string;
        lat: number;
        lon: number;
        name: string;
        days: {
          value: string;
          label: string;
          free: number | null;
          total: number | null;
          isFull: boolean;
        }[];
      }
    >();

    for (const dsd of deliveryStationDays) {
      const lat = dsd.coords_lat != null ? Number(dsd.coords_lat) : NaN;
      const lon = dsd.coords_lon != null ? Number(dsd.coords_lon) : NaN;
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) continue;

      const stationId = String(dsd.delivery_station ?? "");
      if (!stationId) continue;
      const capacity = capacityByDay.get(dsd.value);
      const entry = byStation.get(stationId) ?? {
        stationId,
        lat,
        lon,
        name:
          dsd.delivery_station_name ?? dsd.delivery_station_short_name ?? "",
        days: [],
      };
      entry.days.push({
        value: dsd.value,
        label: dsd.label,
        free: capacity?.free ?? null,
        total: capacity?.total ?? null,
        isFull: capacity?.isFull ?? false,
      });
      byStation.set(stationId, entry);
    }

    return Array.from(byStation.values()).map((station) => ({
      id: station.stationId,
      lat: station.lat,
      lon: station.lon,
      label: station.name,
      selected: station.days.some((day) => day.value === selectedStationDay),
      disabled: station.days.every((day) => day.isFull),
      popup: (
        <div>
          <strong>{station.name}</strong>
          <Flex vertical gap={4} style={{ marginTop: 8 }}>
            {station.days.map((day) => (
              <Button
                key={day.value}
                size="small"
                type={day.value === selectedStationDay ? "primary" : "default"}
                onClick={() =>
                  form.setFieldsValue({
                    default_delivery_station_day: day.value,
                  })
                }
              >
                {day.label}
                {day.isFull
                  ? ` · ${t("abos.station_full_waitlist")}`
                  : day.total != null && day.free != null
                    ? ` · ${t("delivery.free_spots_of_total", {
                        free: day.free,
                        total: day.total,
                      })}`
                    : ""}
              </Button>
            ))}
          </Flex>
        </div>
      ),
    }));
  }, [deliveryStationDays, stationOptions, selectedStationDay, form, t]);

  // Whether the currently-picked station-day is full for the term — the
  // subscription then goes to the waiting list instead of holding capacity.
  const selectedStationIsFull = useMemo(
    () =>
      stationOptions.find((option) => option.value === selectedStationDay)
        ?.isFull ?? false,
    [stationOptions, selectedStationDay],
  );

  const handleSelectVariation = useCallback(
    (variation: ShareTypeVariationOption) => {
      setSelectedVariation(variation);
      form.setFieldsValue({
        price_per_delivery: variation.active_price_per_delivery
          ? Number.parseFloat(variation.active_price_per_delivery)
          : undefined,
      });
    },
    [form],
  );

  const handleBack = useCallback(() => {
    setSelectedVariation(null);
    setWaitlistOffer(false);
    form.resetFields();
  }, [form]);

  const handleCancel = useCallback(() => {
    form.resetFields();
    setSelectedVariation(null);
    setWaitlistOffer(false);
    onCancel();
  }, [form, onCancel]);

  // The SERVER is authoritative on fullness: the create 409s with
  // ``delivery_station.over_capacity`` when the station-day is full for the
  // actual term. The client-side ``selectedStationIsFull`` is only a proactive
  // hint (its capacity_by_week snapshot can be anchored to a different week
  // window than the finally-chosen term) — so on that 409 we OFFER the
  // waitlist and retry with the flag instead of surfacing a dead-end error.
  const performCreate = useCallback(
    async (forceWaitlist: boolean) => {
      if (!selectedVariation) return;

      let values: {
        valid_from: Dayjs;
        valid_until?: Dayjs | null;
        quantity?: number;
        price_per_delivery?: number;
        payment_cycle?: string;
        default_delivery_station_day?: string;
        is_trial?: boolean;
      };
      try {
        values = await form.validateFields();
      } catch {
        return; // antd already surfaced the field errors
      }

      const asWaitlist = forceWaitlist || selectedStationIsFull;
      setSaving(true);
      try {
        const validFromStr = values.valid_from.format("YYYY-MM-DD");
        const validUntilStr = values.valid_until
          ? values.valid_until.format("YYYY-MM-DD")
          : null;
        if (isMemberOnly) {
          // Member self-service: the endpoint takes the member from the token,
          // forces is_trial=false, and (unless solidarity pricing is on) derives
          // price_per_delivery server-side. valid_until is the auto-filled
          // (read-only) term end. The chosen price is only sent when solidarity
          // pricing is enabled; the backend forces the reference price otherwise.
          // A full station-day turns the draft into a waiting-list entry.
          await commissioningMySubscriptionsSubscribeCreate({
            share_type_variation: selectedVariation.value,
            quantity: values.quantity ?? 1,
            payment_cycle: values.payment_cycle ?? "",
            valid_from: validFromStr,
            valid_until: validUntilStr ?? "",
            default_delivery_station_day:
              values.default_delivery_station_day ?? "",
            on_waiting_list: asWaitlist,
            ...(allowsSolidarity && values.price_per_delivery != null
              ? { price_per_delivery: String(values.price_per_delivery) }
              : {}),
          });
        } else {
          const payload: Partial<Subscription> = {
            member: memberId,
            share_type_variation: selectedVariation.value,
            valid_from: validFromStr,
            valid_until: validUntilStr,
            quantity: values.quantity ?? 1,
            price_per_delivery: String(values.price_per_delivery ?? "0.00"),
            payment_cycle: values.payment_cycle,
            default_delivery_station_day: values.default_delivery_station_day,
            is_trial: values.is_trial ?? false,
            on_waiting_list: asWaitlist,
          };
          await commissioningAbosCreate(payload as Subscription);
        }
        setWaitlistOffer(false);
        notify.success(
          asWaitlist
            ? t("abos.subscription_waitlisted")
            : t("members.subscription_created"),
        );
        form.resetFields();
        setSelectedVariation(null);
        onSuccess();
      } catch (error) {
        if (
          !asWaitlist &&
          getErrorCode(error) === "delivery_station.over_capacity"
        ) {
          // Station full for the chosen term — offer the waiting list inline
          // instead of a dead-end error toast.
          setWaitlistOffer(true);
        } else {
          notify.error(getErrorMessage(error, t("common.error")));
          console.error("Failed to create subscription:", error);
        }
      } finally {
        setSaving(false);
      }
    },
    [
      form,
      memberId,
      onSuccess,
      selectedVariation,
      t,
      isMemberOnly,
      allowsSolidarity,
      selectedStationIsFull,
    ],
  );

  const handleSave = useCallback(() => performCreate(false), [performCreate]);

  // valid_from: Monday + not before the tenant's earliest start (handled by
  // ``disabledValidFromDate`` from the shared hook). valid_until: a Sunday on
  // or after valid_from (dayjs: 0=Sun).
  const disableValidUntil = useCallback(
    (d: Dayjs) =>
      d.day() !== 0 || (!!validFrom && d.isBefore(validFrom, "day")),
    [validFrom],
  );

  // valid_from also can't precede the SELECTED variation's own valid_from — a
  // future variation can't be subscribed before it starts. Narrows the shared
  // today+waiting_period rule; never widens it.
  const disableValidFrom = useCallback(
    (current: unknown): boolean => {
      if (disabledValidFromDate(current)) return true;
      const vFrom = selectedVariation?.valid_from;
      return Boolean(
        vFrom && (current as Dayjs)?.isBefore(dayjs(vFrom), "day"),
      );
    },
    [disabledValidFromDate, selectedVariation],
  );

  return (
    <Modal
      title={
        selectedVariation ? (
          <Space>
            <Button
              type="text"
              icon={<ArrowLeftOutlined />}
              onClick={handleBack}
              size="small"
              aria-label={t("common.back")}
            />
            {selectedVariation.share_type_name} –{" "}
            {getShareTypeVariationSizeLabel(selectedVariation.size ?? "")}
          </Space>
        ) : (
          t("members.additional_subscription")
        )
      }
      open={visible}
      onCancel={handleCancel}
      destroyOnHidden
      width={selectedVariation ? 500 : 720}
      footer={
        selectedVariation ? (
          <ModalCancelSaveFooter
            onCancel={handleCancel}
            onPrimary={handleSave}
            loading={saving}
          />
        ) : null
      }
    >
      {!selectedVariation ? (
        /* ── Step 1: visual variation picker ── */
        <div>
          {variationsByType.map((group) => (
            <div key={group.typeName} style={{ marginBottom: 24 }}>
              <Title level={5} style={{ marginBottom: 12 }}>
                {group.typeName}
              </Title>
              <Row gutter={[12, 12]}>
                {group.variations.map((variation) => {
                  const activeQty =
                    activeQuantityByVariation[variation.value] ?? 0;
                  return (
                    <Col xs={24} sm={12} key={variation.value}>
                      <Badge
                        count={activeQty > 0 ? `${activeQty}×` : 0}
                        color="#226c47"
                        offset={[-8, 8]}
                      >
                        <Card
                          hoverable
                          onClick={() => handleSelectVariation(variation)}
                          styles={{ body: { padding: 12 } }}
                          style={{ height: "100%" }}
                        >
                          <Flex gap={12} align="flex-start">
                            {variation.picture ? (
                              <img
                                src={variation.picture}
                                alt={variation.label}
                                className="new-subscription-card-image"
                              />
                            ) : (
                              <div className="new-subscription-card-placeholder">
                                {getShareTypeVariationSizeLabel(
                                  variation.size ?? "",
                                )}
                              </div>
                            )}
                            <div className="flex-min">
                              <Text strong style={{ fontSize: 14 }}>
                                {getShareTypeVariationSizeLabel(
                                  variation.size ?? "",
                                )}
                              </Text>
                              {variation.active_price_per_delivery && (
                                <div>
                                  <Text
                                    type="secondary"
                                    style={{ fontSize: 13 }}
                                  >
                                    {variation.active_price_per_delivery}{" "}
                                    {currencySymbol} / {t("abos.delivery")}
                                  </Text>
                                </div>
                              )}
                              {variation.description && (
                                // Office-authored rich text (HTML) — render +
                                // sanitise instead of printing raw tags. Clamp
                                // to 2 lines for the card preview.
                                <div
                                  style={{
                                    fontSize: 12,
                                    marginTop: 4,
                                    color: "rgba(0, 0, 0, 0.45)",
                                    display: "-webkit-box",
                                    WebkitLineClamp: 2,
                                    WebkitBoxOrient: "vertical",
                                    overflow: "hidden",
                                    overflowWrap: "break-word",
                                  }}
                                  dangerouslySetInnerHTML={{
                                    // Office text often glues words with &nbsp;
                                    // (non-breaking) — swap to normal spaces so
                                    // it wraps at word boundaries, not mid-word.
                                    __html: cleanDescriptionHtml(
                                      variation.description,
                                    ),
                                  }}
                                />
                              )}
                            </div>
                            <CheckCircleFilled
                              style={{
                                color: "var(--color-primary)",
                                fontSize: 20,
                                opacity: activeQty > 0 ? 1 : 0.15,
                              }}
                            />
                          </Flex>
                        </Card>
                      </Badge>
                    </Col>
                  );
                })}
              </Row>
            </div>
          ))}
        </div>
      ) : (
        /* ── Step 2: subscription details form ── */
        <Form
          form={form}
          layout="vertical"
          initialValues={{ quantity: 1, is_trial: false }}
          disabled={saving}
        >
          {selectedVariation.picture && (
            <div style={{ textAlign: "center", marginBottom: 16 }}>
              <img
                src={selectedVariation.picture}
                alt={selectedVariation.label}
                className="new-subscription-detail-image"
              />
            </div>
          )}

          {selectedVariation.description && (
            <Paragraph
              type="secondary"
              style={{ marginBottom: 16, overflowWrap: "break-word" }}
            >
              <span
                dangerouslySetInnerHTML={{
                  __html: cleanDescriptionHtml(selectedVariation.description),
                }}
              />
            </Paragraph>
          )}

          <Row gutter={12}>
            <Col span={12}>
              <Form.Item
                name="valid_from"
                label={t("abos.valid_from")}
                rules={[{ required: true, message: t("common.required") }]}
              >
                <DatePicker
                  className="w-full"
                  format={dateFormat}
                  disabledDate={disableValidFrom}
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="valid_until"
                label={t("abos.valid_until")}
                extra={
                  validUntilHint ? (
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {validUntilHint}
                    </Text>
                  ) : undefined
                }
              >
                <DatePicker
                  className="w-full"
                  format={dateFormat}
                  disabled={lockValidUntil || isMemberOnly}
                  disabledDate={disableValidUntil}
                />
              </Form.Item>
            </Col>
          </Row>

          <Form.Item
            name="default_delivery_station_day"
            label={t("delivery.station")}
            rules={[{ required: true, message: t("common.required") }]}
          >
            <Select
              showSearch
              optionFilterProp="label"
              loading={stationsLoading}
              placeholder={t("delivery.select_station")}
              options={stationOptions}
              optionRender={(option) => {
                const total = option.data.total as number | null;
                const free = option.data.free as number | null;
                const isFull = Boolean(option.data.isFull);
                return (
                  <Flex vertical>
                    <span>
                      {option.label}
                      {isFull && (
                        <Tag color="orange" style={{ marginLeft: 8 }}>
                          {t("abos.station_full_waitlist")}
                        </Tag>
                      )}
                    </span>
                    {!isFull && total != null && free != null && (
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {t("delivery.free_spots_of_total", { free, total })}
                      </Text>
                    )}
                  </Flex>
                );
              }}
            />
          </Form.Item>

          {selectedStationIsFull && !waitlistOffer && (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 16 }}
              message={t("abos.waitlist_notice")}
            />
          )}

          {waitlistOffer && (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 16 }}
              message={t("abos.waitlist_offer_text")}
              action={
                <Button
                  size="small"
                  type="primary"
                  loading={saving}
                  onClick={() => performCreate(true)}
                >
                  {t("abos.waitlist_offer_confirm")}
                </Button>
              }
              closable
              onClose={() => setWaitlistOffer(false)}
            />
          )}

          {stationMarkers.length > 0 && (
            <Form.Item label={t("delivery.map_pick_hint")}>
              <DeliveryStationMap markers={stationMarkers} height={300} />
            </Form.Item>
          )}

          {allowsTrial && !isMemberOnly && (
            <Form.Item
              name="is_trial"
              valuePropName="checked"
              extra={
                isTrial ? (
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {trialEnd
                      ? t("abos.is_trial_hint", { date: formatDate(trialEnd) })
                      : t("abos.is_trial_hint_nodate")}
                  </Text>
                ) : undefined
              }
            >
              <Checkbox>{t("members.is_trial_subscription")}</Checkbox>
              <br />
              {sentenceTrialAbo}
            </Form.Item>
          )}

          <Row gutter={12}>
            <Col span={8}>
              <Form.Item
                name="quantity"
                label={t("members.quantity")}
                rules={[{ required: true, message: t("common.required") }]}
              >
                <InputNumber min={1} className="w-full" />
              </Form.Item>
            </Col>
            <Col span={16}>
              <Form.Item
                name="price_per_delivery"
                label={
                  <>
                    {t("abos.price_per_delivery")}
                    {allowsSolidarity && (
                      <ToolTipIcon
                        title={t("abos.solidarity_pricing_tooltip")}
                      />
                    )}
                  </>
                }
                rules={[{ required: true, message: t("common.required") }]}
                extra={
                  allowsSolidarity && liveVariation?.active_price_per_delivery
                    ? [
                        // Richtpreis (recommended reference price).
                        t("abos.reference_price_hint", {
                          price: Number.parseFloat(
                            liveVariation.active_price_per_delivery,
                          ).toFixed(2),
                          currency: currencySymbol,
                        }),
                        // Untere Grenze (solidarity floor the office/member may
                        // not go below — same value the InputNumber min enforces).
                        liveVariation?.active_solidarity_min_price_per_delivery
                          ? t("abos.solidarity_floor_hint", {
                              price: Number.parseFloat(
                                liveVariation.active_solidarity_min_price_per_delivery,
                              ).toFixed(2),
                              currency: currencySymbol,
                            })
                          : null,
                      ]
                        .filter(Boolean)
                        .join(" · ")
                    : undefined
                }
              >
                <InputNumber
                  // Solidarity floor (variation's solidarity_min, or the
                  // reference if none) AT the chosen valid_from. The backend
                  // re-validates this against the same valid_from window.
                  min={
                    allowsSolidarity
                      ? Number.parseFloat(
                          liveVariation?.active_solidarity_min_price_per_delivery ??
                            liveVariation?.active_price_per_delivery ??
                            "0",
                        )
                      : 0
                  }
                  step={0.01}
                  precision={2}
                  className="w-full"
                  suffix={currencySymbol}
                  // Members can set their own price ONLY when solidarity pricing
                  // is enabled; otherwise it's pre-filled + derived server-side.
                  // Office can always override it.
                  disabled={isMemberOnly && !allowsSolidarity}
                />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item
            name="payment_cycle"
            label={t("abos.payment_cycle")}
            rules={[{ required: true, message: t("common.required") }]}
          >
            <Select
              placeholder={t("abos.select_payment_cycle")}
              options={paymentCycles.map((cycle) => ({
                value: cycle.value,
                label: cycle.label,
              }))}
            />
          </Form.Item>
        </Form>
      )}
    </Modal>
  );
};

export default NewSubscriptionModal;
