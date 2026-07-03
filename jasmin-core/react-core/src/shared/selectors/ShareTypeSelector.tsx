import dayjs from "dayjs";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useIsMobile, useShareTypes } from "@hooks/index";
import BaseEntitySelector, { type SelectorOption } from "./BaseEntitySelector";

interface ShareTypeSelectorProps {
  selectedShareType: string | null;
  setSelectedShareType: (value: string) => void;
  onShareTypeChange?: ((value: string) => void) | null;
  include_null_option?: boolean;
  autoSelectFirst?: boolean;
  /**
   * Reconcile the current pick against the freshly-loaded options when they
   * change (e.g. after a year/week change): keep the selection if it still
   * exists, only fall back to the first option when it's genuinely gone.
   * Defaults to true so a deliberate share-type pick doesn't "spring back"
   * to the first option every time a parent filter changes. (When true it
   * supersedes ``autoSelectFirst`` in BaseEntitySelector.)
   */
  preserveSelection?: boolean;
  year?: number | null;
  delivery_week?: number | null;
  /** When provided, only these share type ids appear as options. Used by the
   *  packing pages to restrict the list to bulk- vs. box-packed share types. */
  allowedShareTypeIds?: Set<string> | null;
}

const ShareTypeSelector = ({
  selectedShareType,
  setSelectedShareType,
  onShareTypeChange = null,
  include_null_option = false,
  autoSelectFirst = true,
  preserveSelection = true,
  year = null,
  delivery_week = null,
  allowedShareTypeIds = null,
}: ShareTypeSelectorProps) => {
  const { t } = useTranslation();
  const isMobile = useIsMobile();

  const activeAtDate = useMemo(() => {
    if (!year || !delivery_week) return undefined;
    return dayjs()
      .year(year)
      .isoWeek(delivery_week)
      .isoWeekday(6)
      .format("YYYY-MM-DD");
  }, [year, delivery_week]);

  const { shareTypes, loading } = useShareTypes(
    activeAtDate ? { active_at_date: activeAtDate } : {},
  );

  const options = useMemo<SelectorOption<string>[]>(() => {
    const opts: SelectorOption<string>[] = [];
    if (include_null_option) opts.push({ value: "none", label: "-" });
    shareTypes
      .filter((st) => !allowedShareTypeIds || allowedShareTypeIds.has(st.value))
      .forEach((st) =>
        opts.push({ value: st.value, label: st.label ?? "" }),
      );
    return opts;
  }, [shareTypes, include_null_option, allowedShareTypeIds]);

  return (
    <BaseEntitySelector<string>
      value={selectedShareType}
      onValueChange={setSelectedShareType}
      onChange={onShareTypeChange}
      options={options}
      loading={loading}
      placeholder={t("placeholder.share_type_selector")}
      style={
        isMobile ? { width: "100%" } : { width: "18em", marginLeft: "2em" }
      }
      autoSelectFirst={autoSelectFirst}
      preserveSelection={preserveSelection}
    />
  );
};

export default ShareTypeSelector;
