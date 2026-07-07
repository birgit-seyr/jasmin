import { ArrowLeftOutlined } from "@ant-design/icons";
import DOMPurify from "dompurify";
import {
  Alert,
  Button,
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
  commissioningConsentsCreate,
  commissioningMySubscriptionsSubscribeCreate,
  useCommissioningDeliveryExceptionPeriodsList,
} from "@shared/api/generated/commissioning/commissioning";
import type { Subscription } from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
import ConsentDocumentField from "@shared/consent/ConsentDocumentField";
import { useCurrentConsentDoc } from "@shared/consent/useCurrentConsentDoc";
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
  capacityWindowParams,
  stationDayTermCapacity,
  termCapacity,
  termWeekKeys,
} from "@features/abos/utils/stationCapacity";
import ShareTypeVariationPickerGrid from "../components/ShareTypeVariationPickerGrid";
import { DeliveryStationMap } from "@shared/ui";
import type { DeliveryStationMapMarker } from "@shared/ui";
import ToolTipIcon from "@shared/ui/ToolTipIcon";
import { notify } from "@shared/utils";
import { getErrorCode, getErrorMessage } from "@shared/utils/apiError";
import SepaSetupModal from "@features/members/modals/SepaSetupModal";
import { usePaymentsBillingProfilesList } from "@shared/api/generated/payments-—-billing-profiles/payments-—-billing-profiles";

const { Text, Paragraph } = Typography;

// Office descriptions are rich text (HTML) and often glue words together with
// non-breaking spaces (the &nbsp; entity OR the U+00A0 char). Sanitise, then
// swap those for normal spaces so the text wraps at word boundaries instead of
// running off as one long line (or being force-broken mid-word).
const cleanDescriptionHtml = (html: string): string =>
  DOMPurify.sanitize(html)
    .replace(/&nbsp;/gi, " ")
    .replace(/\u00a0/g, " ");

export interface SubscriptionIntent {
  share_type_variation_id: string;
  quantity: number;
  valid_from: string;
  valid_until?: string;
  default_delivery_station_day?: string;
  price_per_delivery?: string;
  payment_cycle?: string;
  is_trial: boolean;
  /** Accepted subscription-contract ConsentDocument id, when the tenant
   *  publishes one — the registration wizard records it with the member. */
  accepted_subscription_contract?: string;
}

interface NewSubscriptionModalProps {
  visible: boolean;
  // Required in office/member mode (the write attaches to this member);
  // omitted in "public" mode (registration captures intent, no write).
  memberId?: string;
  subscriptions?: Subscription[];
  onCancel: () => void;
  onSuccess: () => void;
  // "public" = anonymous registration wizard: the same picker + configurator,
  // but NO write — ``onIntent`` is called with the chosen configuration and the
  // office materialises the real subscription on confirm.
  mode?: "office" | "public";
  onIntent?: (intent: SubscriptionIntent) => void;
  // Trial (Probe-Abo) registration: force is_trial=true so ``valid_until`` is
  // the trial end. The toggle is already hidden in public mode.
  forceTrial?: boolean;
}

const NewSubscriptionModal: FC<NewSubscriptionModalProps> = ({
  visible,
  memberId,
  subscriptions = [],
  onCancel,
  onSuccess,
  mode = "office",
  onIntent,
  forceTrial = false,
}) => {
  const { t } = useTranslation();
  const { currencySymbol, formatCurrency } = useCurrency();
  const { dateFormat, formatDate, formatDateForAPI } = useDateFormat();
  const { getShareTypeVariationSizeLabel } = useShareTypeVariationSizeOptions();
  // A member subscribing for THEMSELVES uses the member-scoped endpoint. The
  // price is read-only (derived server-side) UNLESS the tenant allows
  // solidarity pricing, in which case the member may choose it (>= the
  // variation's floor); there's no trial toggle for members either.
  const { isMemberOnly } = useRoles();
  const publicMode = mode === "public";
  // Public registration renders the simplified member view (no office-only
  // fields: trial toggle, payment cycle, valid_until) but never writes.
  const simplified = isMemberOnly || publicMode;
  const { getSetting, tenant } = useTenant();
  // Fall back to the top-level anon-payload scalar (public registration has no
  // settings overlay) so solidarity pricing shows there too.
  const allowsSolidarity = Boolean(
    getSetting("allows_solidarity_pricing") ??
    (tenant as Record<string, unknown> | null)?.allows_solidarity_pricing ??
    false,
  );

  // Subscription-contract consent: shown + required ONLY when the tenant has
  // published a ``subscription_contract`` ConsentDocument (no doc → not
  // required). Recorded on save — office records it on the member's behalf,
  // member/public for the applicant.
  const { doc: subscriptionContractDoc } = useCurrentConsentDoc(
    "subscription_contract",
  );
  const [subscriptionContractAccepted, setSubscriptionContractAccepted] =
    useState(false);
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
    trialDurationInDeliveries,
  } = useSubscriptionTerm();
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);
  const [sepaModalOpen, setSepaModalOpen] = useState(false);

  // SEPA mandate gate (office/member only — public registration sets it up
  // later, post-activation). The subscription can't be saved until the member
  // has a valid mandate; if not, we surface the SAME SepaSetupModal used on the
  // member page. Office reads the member's profile (member filter); a member
  // reads their own (no filter — the endpoint scopes to them).
  const needsSepaMandate = !publicMode && !!memberId;
  const { data: billingProfiles, refetch: refetchBillingProfiles } =
    usePaymentsBillingProfilesList(
      isMemberOnly ? {} : { member: memberId ?? "" },
      { query: { enabled: needsSepaMandate } },
    );
  const sepaReady =
    !needsSepaMandate || Boolean(billingProfiles?.[0]?.is_sepa_ready);
  // Set when the backend refused a NORMAL create with an over-capacity 409 —
  // renders an inline offer to retry as a waiting-list entry. The value records
  // WHICH axis was full (station vs variation) so the offer text matches.
  const [waitingListOffer, setWaitingListOffer] = useState<
    null | "station" | "variation"
  >(null);
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
  // Public registration only offers MAIN share types — an "additional" share
  // (egg/bread top-up etc.) can't be someone's first/only subscription; the
  // office adds those later. Office/member mode still sees everything.
  const offerableShareTypes = publicMode
    ? shareTypes.filter((st) => !st.is_additional_share_type)
    : shareTypes;
  // Literal-typed alias: the interface-based ``ShareTypeOption`` has no
  // implicit index signature, which the hook's index-signed ``ShareTypeRef``
  // parameter requires — this bridges the two without a cast.
  const shareTypeRefs: { id?: string | null }[] = offerableShareTypes;
  const { shareTypeVariations } = useAllShareTypeVariations(shareTypeRefs, {
    active_at_date: pricingDate,
    include_future: true,
    // Wide capacity window so each variation carries capacity_by_week for the
    // term-aware sold-out check below — the SAME window the station-days and
    // the Abos table use.
    ...capacityWindowParams(),
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
  // Watched so the fullness checks are quantity-aware: a full-enough station /
  // variation for THIS many shares waiting_lists, matching the backend gate.
  const quantity = (Form.useWatch("quantity", form) as number | undefined) ?? 1;
  const validFromMs = validFrom ? validFrom.valueOf() : null;
  const validUntilMs = validUntil ? validUntil.valueOf() : null;

  // Lieferpausen (delivery pauses) for the chosen variation that fall inside
  // the chosen [valid_from, valid_until] term. Anon/public reads are allowed
  // for an explicit variation filter (see DeliveryExceptionPeriodViewSet).
  const { data: exceptionPeriods } =
    useCommissioningDeliveryExceptionPeriodsList(
      {
        share_type_variation: selectedVariation
          ? String(selectedVariation.value)
          : "",
      },
      { query: { enabled: !!selectedVariation } },
    );
  const pausesInTerm = useMemo(() => {
    if (!validFrom || !exceptionPeriods) return [];
    const rangeEnd = validUntil ?? validFrom.add(1, "year");
    return exceptionPeriods.filter((p) => {
      // Overlap: pause starts on/before range end AND ends on/after range start.
      return (
        !dayjs(p.valid_from).isAfter(rangeEnd, "day") &&
        !dayjs(p.valid_until).isBefore(validFrom, "day")
      );
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [exceptionPeriods, validFromMs, validUntilMs]);

  // Every ``"<iso-year>-<iso-week>"`` key in the term — via the SHARED
  // ``termWeekKeys`` so the modal's fullness evaluation matches the Abos select,
  // the capacity overview, and the backend for the same term (no bespoke week
  // math that could disagree). Open-ended terms span a one-year window.
  const periodWeekKeys = useMemo(
    () => termWeekKeys(validFrom ?? dayjs(), validUntil ?? null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [validFromMs, validUntilMs],
  );

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

  // The effective trial flag. In public mode the is_trial checkbox is hidden,
  // so the form field never reflects ``forceTrial`` — honour the prop directly
  // there (otherwise the term math would fall through to the one-year branch).
  const effectiveIsTrial = publicMode ? forceTrial === true : isTrial === true;

  // ``valid_until`` is read-only + auto-filled when the tenant config fully
  // determines it (trial duration, season end, or one-year term). Otherwise
  // it's a free Sunday the office types.
  const lockValidUntil = isValidUntilAuto(effectiveIsTrial);

  useEffect(() => {
    if (!lockValidUntil || !validFrom) return;
    const until = computeValidUntil(validFrom, {
      isTrial: effectiveIsTrial,
      cycle: variationCycle,
    });
    form.setFieldsValue({ valid_until: until ?? undefined });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lockValidUntil, validFromMs, effectiveIsTrial, variationCycle]);

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
  // a full tag or a waiting_list offer.
  const termKnown = Boolean(validFrom && validUntil);
  const capacityRelevant = useMemo(() => {
    if (!selectedVariation) return false;
    const shareType = shareTypes.find(
      (candidate) =>
        String(candidate.value) === String(selectedVariation.share_type),
    );
    // Capacity applies to STANDALONE (non-additional) shares only — add-ons
    // (chicken, honey, …) ride along in the base box and never consume a slot.
    // Mirrors the backend is_additional_share_type capacity gate.
    return shareType ? !shareType.is_additional_share_type : false;
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
            quantity,
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
  }, [deliveryStationDays, periodWeekKeys, showCapacity, quantity]);

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
                  ? ` · ${t("abos.station_full_waiting_list")}`
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

  // The OTHER capacity axis: the variation's farm-wide production cap is full
  // for the term — its busiest ("peak") ISO week has no free slot. Uses the
  // SAME per-week ``capacity_by_week`` + ``termCapacity`` evaluator as the
  // station-day above (and the Abos select + capacity overview), so what the
  // office sees here matches what the backend blocks. ``null`` cap = unlimited.
  const selectedVariationIsFull = useMemo(
    () =>
      termCapacity(
        liveVariation?.capacity,
        liveVariation?.capacity_by_week,
        periodWeekKeys,
        quantity,
      ).isFull,
    [
      liveVariation?.capacity,
      liveVariation?.capacity_by_week,
      periodWeekKeys,
      quantity,
    ],
  );

  // Either capacity gate being full routes the order to the waiting list.
  const isFullForTerm = selectedStationIsFull || selectedVariationIsFull;

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
    setWaitingListOffer(null);
    form.resetFields();
  }, [form]);

  const handleCancel = useCallback(() => {
    form.resetFields();
    setSelectedVariation(null);
    setWaitingListOffer(null);
    setSubscriptionContractAccepted(false);
    onCancel();
  }, [form, onCancel]);

  // The SERVER is authoritative on fullness: the create 409s with
  // ``delivery_station.over_capacity`` when the station-day is full for the
  // actual term. The client-side ``selectedStationIsFull`` is only a proactive
  // hint (its capacity_by_week snapshot can be anchored to a different week
  // window than the finally-chosen term) — so on that 409 we OFFER the
  // waiting_list and retry with the flag instead of surfacing a dead-end error.
  const performCreate = useCallback(
    async (forceWaitingList: boolean) => {
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

      // Block until the subscription contract is accepted (only when the tenant
      // publishes one). Applies to every mode — public intent, office, member.
      if (subscriptionContractDoc && !subscriptionContractAccepted) {
        notify.error(t("abos.subscription_contract_required"));
        return;
      }

      // Public registration: no write — hand the chosen configuration back to
      // the wizard as intent. The office materialises the real (capacity-
      // checked) subscription on confirm.
      if (publicMode) {
        onIntent?.({
          share_type_variation_id: String(selectedVariation.value),
          quantity: values.quantity ?? 1,
          valid_from: formatDateForAPI(values.valid_from) ?? "",
          valid_until: formatDateForAPI(values.valid_until) ?? undefined,
          default_delivery_station_day:
            values.default_delivery_station_day || undefined,
          price_per_delivery:
            values.price_per_delivery != null
              ? String(values.price_per_delivery)
              : undefined,
          payment_cycle: values.payment_cycle || undefined,
          is_trial: forceTrial === true,
          accepted_subscription_contract: subscriptionContractDoc?.id,
        });
        form.resetFields();
        setSelectedVariation(null);
        setSubscriptionContractAccepted(false);
        onSuccess();
        return;
      }

      // No subscription without a valid SEPA mandate — surface the setup modal
      // (the same one used on the member page) instead of writing.
      if (!sepaReady) {
        notify.error(t("abos.sepa_mandate_required"));
        setSepaModalOpen(true);
        return;
      }

      const asWaitingList = forceWaitingList || isFullForTerm;
      setSaving(true);
      try {
        const validFromStr = formatDateForAPI(values.valid_from) ?? "";
        const validUntilStr = formatDateForAPI(values.valid_until);
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
            on_waiting_list: asWaitingList,
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
            on_waiting_list: asWaitingList,
          };
          await commissioningAbosCreate(payload as Subscription);
        }
        // Record the subscription-contract consent once the subscription
        // exists. Office records it on the member's behalf (``member``);
        // a member self-subscribing is pinned to their own record server-side.
        // Non-fatal: the subscription is already saved, so a failed consent
        // write only warns rather than rolling back.
        if (subscriptionContractDoc?.id && subscriptionContractAccepted) {
          try {
            await commissioningConsentsCreate({
              document_id: subscriptionContractDoc.id,
              ...(isMemberOnly ? {} : { member: memberId }),
            });
          } catch (consentError) {
            console.error(
              "Failed to record subscription-contract consent:",
              consentError,
            );
            notify.warning(t("abos.subscription_contract_record_failed"));
          }
        }
        setWaitingListOffer(null);
        notify.success(
          asWaitingList
            ? t("abos.subscription_waiting_listed")
            : t("members.subscription_created"),
        );
        form.resetFields();
        setSelectedVariation(null);
        setSubscriptionContractAccepted(false);
        onSuccess();
      } catch (error) {
        const code = getErrorCode(error);
        if (
          !asWaitingList &&
          (code === "delivery_station.over_capacity" ||
            code === "share_type_variation.over_capacity")
        ) {
          // Station-day OR variation full for the chosen term — offer the
          // waiting list inline instead of a dead-end error toast.
          setWaitingListOffer(
            code === "share_type_variation.over_capacity"
              ? "variation"
              : "station",
          );
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
      isFullForTerm,
      publicMode,
      onIntent,
      forceTrial,
      sepaReady,
      subscriptionContractDoc,
      subscriptionContractAccepted,
      formatDateForAPI,
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
    <>
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
            // The Abo-Vertrag consent is mandatory: keep the primary button
            // greyed out (not green) until it's ticked when the tenant
            // publishes one.
            primaryDisabled={Boolean(
              subscriptionContractDoc && !subscriptionContractAccepted,
            )}
          />
        ) : null
      }
    >
      {!selectedVariation ? (
        /* ── Step 1: visual variation picker ── */
        <ShareTypeVariationPickerGrid
          variations={shareTypeVariations}
          onSelect={handleSelectVariation}
          activeQuantityByVariation={activeQuantityByVariation}
        />
      ) : (
        /* ── Step 2: subscription details form ── */
        <Form
          form={form}
          layout="vertical"
          initialValues={{ quantity: 1, is_trial: forceTrial }}
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

          {/* is_trial FIRST: it changes valid_from's earliest date + the
              auto-filled valid_until (trial end), so the applicant/office
              decides trial before the dates. */}
          {allowsTrial && !simplified && (
            <>
              <Form.Item
                name="is_trial"
                valuePropName="checked"
                style={{ marginBottom: sentenceTrialAbo ? 4 : undefined }}
                extra={
                  isTrial ? (
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {trialEnd
                        ? t("abos.is_trial_hint", {
                            date: formatDate(trialEnd),
                          })
                        : t("abos.is_trial_hint_nodate")}
                    </Text>
                  ) : undefined
                }
              >
                {/* MUST be the Form.Item's ONLY child — with extra siblings
                    AntD won't bind ``checked``, so the toggle wouldn't update
                    is_trial (and valid_until wouldn't recompute). */}
                <Checkbox>
                  {trialDurationInDeliveries != null
                    ? t("members.trial_subscription_weeks", {
                        weeks: trialDurationInDeliveries,
                      })
                    : t("members.is_trial_subscription")}
                </Checkbox>
              </Form.Item>
              {sentenceTrialAbo && (
                <Paragraph type="secondary" style={{ fontSize: 12 }}>
                  {sentenceTrialAbo}
                </Paragraph>
              )}
            </>
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
                // A subscription must have an end date (the backend rejects
                // open-ended ones). Disable + skip the required rule ONLY when
                // it's auto-filled + locked (a tenant term rule populates it).
                // Without a term rule the auto-fill never runs, so even in the
                // simplified member/public view the field must stay editable +
                // required — otherwise it's disabled, empty and unvalidated and
                // the member dead-ends on a raw 400.
                rules={
                  lockValidUntil
                    ? undefined
                    : [{ required: true, message: t("common.required") }]
                }
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
                  disabled={lockValidUntil}
                  disabledDate={disableValidUntil}
                />
              </Form.Item>
            </Col>
          </Row>

          {pausesInTerm.length > 0 && (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 16 }}
              message={t("abos.delivery_pauses_in_term")}
              description={
                <ul style={{ margin: 0, paddingLeft: 18 }}>
                  {pausesInTerm.map((p) => (
                    <li key={`${p.share_type_variation}-${p.valid_from}`}>
                      {formatDate(p.valid_from)} – {formatDate(p.valid_until)}
                      {p.note ? ` — ${p.note}` : ""}
                    </li>
                  ))}
                </ul>
              }
            />
          )}

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
                          {t("abos.station_full_waiting_list")}
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

          {isFullForTerm && !waitingListOffer && (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 16 }}
              message={
                selectedVariationIsFull
                  ? t("abos.waiting_list_notice_variation")
                  : t("abos.waiting_list_notice")
              }
            />
          )}

          {waitingListOffer && (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 16 }}
              message={
                waitingListOffer === "variation"
                  ? t("abos.waiting_list_offer_text_variation")
                  : t("abos.waiting_list_offer_text")
              }
              action={
                <Button
                  size="small"
                  type="primary"
                  loading={saving}
                  onClick={() => performCreate(true)}
                >
                  {t("abos.waiting_list_offer_confirm")}
                </Button>
              }
              closable
              onClose={() => setWaitingListOffer(null)}
            />
          )}

          {stationMarkers.length > 0 && (
            <Form.Item label={t("delivery.map_pick_hint")}>
              <DeliveryStationMap markers={stationMarkers} height={300} />
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
                // Only require when the field is editable. In the simplified
                // member/public view without solidarity pricing the price is
                // disabled + prefilled from the variation; attaching a required
                // rule to that disabled field would show an unclearable inline
                // error under a greyed input for an unpriced variation.
                rules={
                  simplified && !allowsSolidarity
                    ? undefined
                    : [{ required: true, message: t("common.required") }]
                }
                extra={
                  allowsSolidarity && liveVariation?.active_price_per_delivery
                    ? [
                        // Richtpreis (recommended reference price).
                        t("abos.reference_price_hint", {
                          price: formatCurrency(
                            Number.parseFloat(
                              liveVariation.active_price_per_delivery,
                            ),
                          ),
                        }),
                        // Untere Grenze (solidarity floor the office/member may
                        // not go below — same value the InputNumber min enforces).
                        liveVariation?.active_solidarity_min_price_per_delivery
                          ? t("abos.solidarity_floor_hint", {
                              price: formatCurrency(
                                Number.parseFloat(
                                  liveVariation.active_solidarity_min_price_per_delivery,
                                ),
                              ),
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
                  disabled={simplified && !allowsSolidarity}
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
          <Text type="secondary">{t("abos.payment_method_sepa")}</Text>
          {publicMode && (
            <Alert
              type="info"
              showIcon
              style={{ marginTop: 12 }}
              message={t("abos.public_sepa_mandate_hint")}
            />
          )}
          {needsSepaMandate && !sepaReady && (
            <Alert
              type="warning"
              showIcon
              style={{ marginTop: 12 }}
              message={t("abos.sepa_mandate_missing")}
              action={
                <Button
                  size="small"
                  type="primary"
                  onClick={() => setSepaModalOpen(true)}
                >
                  {t("abos.set_up_sepa_mandate")}
                </Button>
              }
            />
          )}

          {/* Subscription-contract consent — only when the tenant publishes
              one; required before the subscription can be saved (all modes). */}
          {subscriptionContractDoc && (
            <div style={{ marginTop: 16 }}>
              <ConsentDocumentField
                doc={subscriptionContractDoc}
                accepted={subscriptionContractAccepted}
                onChange={setSubscriptionContractAccepted}
                labelKey="abos.accept_subscription_contract"
              />
            </div>
          )}
        </Form>
      )}
    </Modal>
    {needsSepaMandate && memberId && (
      <SepaSetupModal
        open={sepaModalOpen}
        memberId={memberId}
        onClose={() => {
          setSepaModalOpen(false);
          refetchBillingProfiles();
        }}
      />
    )}
    </>
  );
};

export default NewSubscriptionModal;
