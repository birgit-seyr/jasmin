import { useCallback, useState } from "react";
import type { Key } from "react";
import { useTranslation } from "react-i18next";
import { commissioningHarvestPartialUpdate } from "@shared/api/generated/commissioning/commissioning";
import type { DayNumberEnum, Harvest } from "@shared/api/generated/models";
import type { TableRecord } from "@shared/tables/BasicEditableTable/types";
import { notify } from "@shared/utils";
import { getServerErrorMessage } from "@shared/utils/apiError";
import { roundHalfUp } from "@shared/utils/lineNetto";

/** The writable ``Harvest`` fields a confirmation patches. */
type HarvestConfirmationPatch = Pick<
  Harvest,
  "amount" | "year" | "delivery_week" | "day_number"
>;

/**
 * Manages the "confirm harvest" modal state for the harvesting list mobile
 * view: which record is being confirmed, the input amount, save state and
 * the in-memory set of already-confirmed keys (so the button colour switches
 * to green immediately, even before the data refetches). A refused save
 * keeps the dialog open with its amount and tells the user why.
 */
export function useHarvestConfirmation(params: {
  selectedYear: number;
  selectedWeek: number | null;
  selectedDay: DayNumberEnum | null;
  fallbackWeek: number;
  onSaved: () => void;
}) {
  const { selectedYear, selectedWeek, selectedDay, fallbackWeek, onSaved } =
    params;
  const { t } = useTranslation();

  const [record, setRecord] = useState<TableRecord | null>(null);
  const [amount, setAmount] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirmedKeys, setConfirmedKeys] = useState<Set<Key>>(
    new Set(),
  );

  const open = useCallback((rec: TableRecord) => {
    setRecord(rec);
    const expected = (rec.computed_total_amount as number) || 0;
    const existing = rec.harvest_amount as number | string | null | undefined;
    // The server keeps a harvest to two decimals, and the field shows it so.
    // The expected amount comes from plans kept to three decimals and is
    // summed in floats (10.2 - 3.4 is 6.799999999999999), so the dialog starts
    // from the amount the field shows, rounded half up as the field rounds it
    // (toFixed rounds 1.005 down); an untouched confirm would otherwise send
    // one the server refuses.
    setAmount(roundHalfUp(Number(existing ?? expected), 2));
  }, []);

  const close = useCallback(() => {
    setRecord(null);
    setAmount(null);
  }, []);

  const confirm = useCallback(async () => {
    if (!record) return;
    setSaving(true);
    try {
      const confirmation: HarvestConfirmationPatch = {
        amount: (amount ?? 0).toFixed(2),
        year: selectedYear,
        delivery_week: selectedWeek ?? fallbackWeek,
        day_number: selectedDay ?? 0,
      };
      // The schema has no separate PATCH body type, so the generated
      // partial update asks for a whole Harvest; a PATCH sends only these.
      await commissioningHarvestPartialUpdate(
        String(record.key),
        confirmation as Harvest,
      );
      setConfirmedKeys((prev) => new Set(prev).add(record.key));
      onSaved();
      close();
    } catch (err) {
      notify.error(
        getServerErrorMessage(err) ?? t("commissioning.harvest_save_failed"),
      );
    } finally {
      setSaving(false);
    }
  }, [
    record,
    amount,
    selectedYear,
    selectedWeek,
    selectedDay,
    fallbackWeek,
    onSaved,
    close,
    t,
  ]);

  const isConfirmed = useCallback(
    (rec: TableRecord) =>
      confirmedKeys.has(rec.key) ||
      ((rec.harvest_amount as number | null | undefined) != null &&
        (rec.harvest_amount as number) > 0),
    [confirmedKeys],
  );

  return {
    record,
    amount,
    setAmount,
    saving,
    open,
    close,
    confirm,
    isConfirmed,
  };
}
