import { useCallback, useState } from "react";
import type { Key } from "react";
import { commissioningHarvestPartialUpdate } from "@shared/api/generated/commissioning/commissioning";
import type { Harvest } from "@shared/api/generated/models";
import type { TableRecord } from "@shared/tables/BasicEditableTable/types";

/**
 * Manages the "confirm harvest" modal state for the harvesting list mobile
 * view: which record is being confirmed, the input amount, save state and
 * the in-memory set of already-confirmed keys (so the button colour switches
 * to green immediately, even before the data refetches).
 */
export function useHarvestConfirmation(params: {
  selectedYear: number;
  selectedWeek: number | null;
  selectedDay: number | null;
  fallbackWeek: number;
  onSaved: () => void;
}) {
  const { selectedYear, selectedWeek, selectedDay, fallbackWeek, onSaved } =
    params;

  const [record, setRecord] = useState<TableRecord | null>(null);
  const [amount, setAmount] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirmedKeys, setConfirmedKeys] = useState<Set<Key>>(
    new Set(),
  );

  const open = useCallback((rec: TableRecord) => {
    setRecord(rec);
    const expected = (rec.computed_total_amount as number) || 0;
    const existing = rec.harvest_amount as number | null | undefined;
    setAmount(existing ?? expected);
  }, []);

  const close = useCallback(() => {
    setRecord(null);
    setAmount(null);
  }, []);

  const confirm = useCallback(async () => {
    if (!record) return;
    setSaving(true);
    try {
      await commissioningHarvestPartialUpdate(
        String(record.key),
        {
          amount: amount ?? 0,
          year: selectedYear,
          delivery_week: selectedWeek ?? fallbackWeek,
          day_number: selectedDay ?? 0,
        } as unknown as Harvest,
      );
      setConfirmedKeys((prev) => new Set(prev).add(record.key));
      onSaved();
      close();
    } catch (err) {
       
      console.error("Failed to save harvest amount:", err);
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
