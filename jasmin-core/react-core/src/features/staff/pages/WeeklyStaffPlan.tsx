import { Button, Select, message } from "antd";
import dayjs from "dayjs";
import isoWeek from "dayjs/plugin/isoWeek";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";

import {
  getStaffWeeklyPlanGridRetrieveQueryKey,
  useStaffWeeklyPlanCopyCreate,
  useStaffWeeklyPlanCreate,
  useStaffWeeklyPlanGridRetrieve,
} from "@shared/api/generated/staff/staff";
import type { WeeklyPlanEmployee } from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
import { WeekSelector } from "@shared/selectors";
import {
  AutoSaveIndicator,
  DndGrid,
  DraggableChip,
  DroppableCell,
  usePastelColorMap,
} from "@shared/ui";
import type { DndDragPayload, GridPos } from "@shared/ui";
import { getErrorMessage } from "@shared/utils/apiError";

dayjs.extend(isoWeek);

const WEEKDAYS = [0, 1, 2, 3, 4, 5, 6];

/** A flat grid row: which category + which line inside it. ``pos.row`` indexes
 *  into the flat list; ``pos.col`` is the weekday. */
interface FlatRow {
  categoryId: string;
  rowIndex: number;
}

const cellKey = (categoryId: string, rowIndex: number, day: number) =>
  `${categoryId}|${rowIndex}|${day}`;

/** True if any employee appears more than once in the same (category, day) —
 *  the invariant we enforce: a person may work several categories/days, but not
 *  the same category twice on one day (across rows). */
function hasCategoryDayDuplicate(state: Record<string, string>): boolean {
  const seen = new Set<string>();
  for (const [key, employeeId] of Object.entries(state)) {
    const [categoryId, , day] = key.split("|");
    const slot = `${categoryId}|${day}|${employeeId}`;
    if (seen.has(slot)) return true;
    seen.add(slot);
  }
  return false;
}

export default function WeeklyStaffPlan() {
  const { t } = useTranslation();
  const { isOffice } = useRoles();
  const queryClient = useQueryClient();

  const [selectedYear, setSelectedYear] = useState<number>(() =>
    dayjs().year(),
  );
  const [selectedWeek, setSelectedWeek] = useState<number | null>(() =>
    dayjs().isoWeek(),
  );
  const [copyFromWeek, setCopyFromWeek] = useState<number | null>(null);

  // Reset the manual source-week choice when the target week changes so the
  // picker always re-defaults to "previous week" for the new selection.
  useEffect(() => {
    setCopyFromWeek(null);
  }, [selectedYear, selectedWeek]);

  const listParams = useMemo(
    () => ({ year: selectedYear, week: selectedWeek ?? 1 }),
    [selectedYear, selectedWeek],
  );

  const { data: grid, isFetching } = useStaffWeeklyPlanGridRetrieve(
    listParams,
    {
      query: { enabled: selectedWeek != null },
    },
  );

  // Editable grid state: filled cells only, keyed by `${category}|${row}|${day}`.
  const [cells, setCells] = useState<Record<string, string>>({});
  // Freshest cells for the DnD handlers (they run on DOM events, not in render).
  const cellsRef = useRef(cells);
  cellsRef.current = cells;

  // Only a genuine user edit (place / remove / move) should POST — NOT the load
  // effect that seeds `cells` from a freshly-fetched week. A ref the edit
  // handlers set flags real edits (mirrors the DeliveryTours pattern).
  const userEditedRef = useRef(false);

  // Seed local state whenever a new week's grid arrives.
  useEffect(() => {
    if (!grid) return;
    const seeded: Record<string, string> = {};
    grid.categories.forEach((category) =>
      category.rows.forEach((row) =>
        Object.entries(row.days).forEach(([day, employeeId]) => {
          if (employeeId) {
            seeded[cellKey(category.id, row.row_index, Number(day))] =
              employeeId;
          }
        }),
      ),
    );
    setCells(seeded);
  }, [grid]);

  const employees: WeeklyPlanEmployee[] = useMemo(
    () => grid?.employees ?? [],
    [grid],
  );
  const employeeById = useMemo(
    () => new Map(employees.map((e) => [e.id, e])),
    [employees],
  );
  const colorMap = usePastelColorMap(
    useMemo(() => employees.map((e) => e.id), [employees]),
  );

  // Live tally of how many cells each employee fills in the visible week —
  // shown as a small badge on their palette chip.
  const planCountByEmployee = useMemo(() => {
    const counts = new Map<string, number>();
    for (const employeeId of Object.values(cells)) {
      counts.set(employeeId, (counts.get(employeeId) ?? 0) + 1);
    }
    return counts;
  }, [cells]);

  // Flat row list (for pos.row) + its reverse (category,row → flat index).
  const flatRows = useMemo<FlatRow[]>(() => {
    const rows: FlatRow[] = [];
    grid?.categories.forEach((category) => {
      for (let rowIndex = 0; rowIndex < category.max_lines; rowIndex++) {
        rows.push({ categoryId: category.id, rowIndex });
      }
    });
    return rows;
  }, [grid]);
  const flatRowsRef = useRef<FlatRow[]>([]);
  flatRowsRef.current = flatRows;
  const flatIndexByCell = useMemo(() => {
    const map = new Map<string, number>();
    flatRows.forEach((r, index) =>
      map.set(`${r.categoryId}|${r.rowIndex}`, index),
    );
    return map;
  }, [flatRows]);

  const { mutate: save, isPending: isSaving } = useStaffWeeklyPlanCreate({
    mutation: {
      onError: (error) => {
        message.error(getErrorMessage(error, t("staff.save_failed")));
        // Re-sync so the UI can't keep showing an unsaved plan.
        queryClient.invalidateQueries({
          queryKey: getStaffWeeklyPlanGridRetrieveQueryKey(listParams),
        });
      },
    },
  });

  // Auto-save the whole week on any real edit (last-write-wins replace-all).
  useEffect(() => {
    if (!userEditedRef.current) return;
    userEditedRef.current = false;
    if (selectedWeek == null) return;
    const assignments = Object.entries(cells).map(([key, employeeId]) => {
      const [categoryId, rowIndex, day] = key.split("|");
      return {
        category_id: categoryId,
        row_index: Number(rowIndex),
        day: Number(day),
        employee_id: employeeId,
      };
    });
    save({
      data: { year: selectedYear, week: selectedWeek, assignments },
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cells]);

  const handlePlace = useCallback(
    (payload: DndDragPayload, to: GridPos) => {
      const target = flatRowsRef.current[to.row];
      if (!target) return;

      const next = { ...cellsRef.current };
      const targetKey = cellKey(target.categoryId, target.rowIndex, to.col);
      if (payload.from) {
        const source = flatRowsRef.current[payload.from.row];
        if (!source) return;
        const sourceKey = cellKey(
          source.categoryId,
          source.rowIndex,
          payload.from.col,
        );
        const moved = next[sourceKey];
        if (moved === undefined) return;
        const displaced = next[targetKey];
        delete next[sourceKey];
        next[targetKey] = moved;
        // Swap: the target's previous occupant falls back into the source cell.
        if (displaced !== undefined) next[sourceKey] = displaced;
      } else {
        // From the palette: repeatable ACROSS categories/days — an employee may
        // fill many cells, just not the same category twice on one day.
        next[targetKey] = payload.chip.id;
      }

      // Enforce the one-per-category-per-day rule client-side: reject the drop
      // (leave the grid untouched) rather than create a duplicate.
      if (hasCategoryDayDuplicate(next)) {
        message.warning(t("staff.already_in_category_that_day"));
        return;
      }

      userEditedRef.current = true;
      setCells(next);
    },
    [t],
  );

  const handleRemove = useCallback((pos: GridPos) => {
    const target = flatRowsRef.current[pos.row];
    if (!target) return;
    userEditedRef.current = true;
    setCells((prev) => {
      const next = { ...prev };
      delete next[cellKey(target.categoryId, target.rowIndex, pos.col)];
      return next;
    });
  }, []);

  const currentWeekIsEmpty = Object.keys(cells).length === 0;

  // Focus the grid region after a copy: the Copy button gets disabled once the
  // week is no longer empty, so keyboard focus would otherwise be lost.
  const gridRegionRef = useRef<HTMLElement>(null);

  // Copy source: default to the previous week (same year); the office can pick
  // another from the dropdown. ``effectiveFromWeek`` is what a copy uses.
  const defaultFromWeek =
    selectedWeek != null && selectedWeek > 1 ? selectedWeek - 1 : null;
  const effectiveFromWeek = copyFromWeek ?? defaultFromWeek;

  const weekOptions = useMemo(() => {
    // Dec 28 always falls in the last ISO week of its year → its week number is
    // the count of ISO weeks (52 or 53), using only the isoWeek plugin.
    const totalWeeks = dayjs(`${selectedYear}-12-28`).isoWeek();
    return Array.from({ length: totalWeeks }, (_, i) => i + 1)
      .filter((week) => week !== selectedWeek)
      .map((week) => ({
        value: week,
        label: t("staff.week_option", { week }),
      }));
  }, [selectedYear, selectedWeek, t]);

  const { mutate: copyWeek, isPending: isCopying } =
    useStaffWeeklyPlanCopyCreate({
      mutation: {
        onSuccess: () => {
          message.success(t("staff.weekly_plan_copied_success"));
          queryClient.invalidateQueries({
            queryKey: getStaffWeeklyPlanGridRetrieveQueryKey(listParams),
          });
          gridRegionRef.current?.focus();
        },
        onError: (error) => {
          message.error(
            getErrorMessage(error, t("staff.copy_target_not_empty")),
          );
        },
      },
    });

  const handleCopy = () => {
    if (selectedWeek == null || effectiveFromWeek == null) return;
    copyWeek({
      data: {
        year: selectedYear,
        from_week: effectiveFromWeek,
        to_week: selectedWeek,
      },
    });
  };

  const hasCategories = (grid?.categories.length ?? 0) > 0;

  return (
    <>
      <h1>{t("staff.weekly_staff_plan")}</h1>
      <AutoSaveIndicator saving={isSaving} hasChanges={false} />
      <WeekSelector
        selectedYear={selectedYear}
        setSelectedYear={setSelectedYear}
        selectedWeek={selectedWeek}
        setSelectedWeek={setSelectedWeek}
      />
      {isOffice && selectedWeek != null && currentWeekIsEmpty && (
        <div className="weekly-plan-toolbar">
          <div className="weekly-plan-copy">
            <label className="weekly-plan-copy-field">
              {t("staff.copy_weekly_plan_from")}
              <Select
                aria-label={t("staff.copy_weekly_plan_from")}
                size="small"
                showSearch
                optionFilterProp="label"
                style={{ minWidth: "8em" }}
                placeholder={t("staff.copy_source_week")}
                value={effectiveFromWeek ?? undefined}
                onChange={(value) => setCopyFromWeek(value)}
                options={weekOptions}
              />
            </label>
            <Button
              type="primary"
              size="small"
              onClick={handleCopy}
              loading={isCopying}
              disabled={effectiveFromWeek == null}
            >
              {t("staff.copy_into_this_week")}
            </Button>
          </div>
        </div>
      )}
      <DndGrid onPlace={handlePlace} onRemove={handleRemove}>
        <div className="weekly-plan-page">
          {selectedWeek == null ? (
            <p className="text-muted">{t("staff.select_week")}</p>
          ) : !hasCategories ? (
            <p className="text-muted">{t("staff.no_categories")}</p>
          ) : (
            <div className="weekly-plan-layout">
              <section
                className="weekly-plan-palette"
                aria-labelledby="weekly-plan-employees-heading"
              >
                <h3 id="weekly-plan-employees-heading">
                  {t("staff.employees")}
                </h3>
                <div className="weekly-plan-palette-box">
                  {employees.length === 0 ? (
                    <p className="text-muted">{t("staff.no_employees")}</p>
                  ) : (
                    employees.map((employee) => {
                      const count = planCountByEmployee.get(employee.id) ?? 0;
                      return (
                        <DraggableChip
                          key={employee.id}
                          chip={{
                            id: employee.id,
                            label: employee.short_name_for_weekly_plan,
                            color: colorMap.get(employee.id),
                          }}
                          canDrag={isOffice}
                          count={count}
                          ariaHint={t("staff.times_planned", { count })}
                        />
                      );
                    })
                  )}
                </div>
              </section>

              <section
                className="weekly-plan-grid-wrap"
                aria-label={t("staff.grid_caption", {
                  week: selectedWeek,
                  year: selectedYear,
                })}
                tabIndex={-1}
                ref={gridRegionRef}
              >
                <table
                  className="weekly-plan-grid-table"
                  aria-label={t("staff.grid_caption", {
                    week: selectedWeek,
                    year: selectedYear,
                  })}
                >
                  <thead>
                    <tr>
                      <th className="weekly-plan-th-row-label" scope="col" />
                      {WEEKDAYS.map((day) => (
                        <th key={day} scope="col">
                          {t(`commissioning.weekdays.${day}`)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  {grid?.categories.map((category) => (
                    <tbody
                      key={category.id}
                      className="weekly-plan-category-group"
                    >
                      <tr className="weekly-plan-category-row">
                        <th colSpan={WEEKDAYS.length + 1} scope="colgroup">
                          {category.name}
                        </th>
                      </tr>
                      {Array.from(
                        { length: category.max_lines },
                        (_, rowIndex) => (
                          <tr key={`${category.id}-${rowIndex}`}>
                            <th className="weekly-plan-row-label" scope="row">
                              {rowIndex + 1}
                            </th>
                            {WEEKDAYS.map((day) => {
                              const employeeId =
                                cells[cellKey(category.id, rowIndex, day)];
                              const employee = employeeId
                                ? employeeById.get(employeeId)
                                : null;
                              const flatIndex =
                                flatIndexByCell.get(
                                  `${category.id}|${rowIndex}`,
                                ) ?? 0;
                              const dayName = t(
                                `commissioning.weekdays.${day}`,
                              );
                              const cellAriaLabel = employee
                                ? t("staff.cell_filled", {
                                    day: dayName,
                                    category: category.name,
                                    row: rowIndex + 1,
                                    employee:
                                      employee.short_name_for_weekly_plan,
                                  })
                                : t("staff.cell_empty", {
                                    day: dayName,
                                    category: category.name,
                                    row: rowIndex + 1,
                                  });
                              return (
                                <td key={day} className="weekly-plan-cell">
                                  <DroppableCell
                                    pos={{ row: flatIndex, col: day }}
                                    occupant={
                                      employee
                                        ? {
                                            id: employee.id,
                                            label:
                                              employee.short_name_for_weekly_plan,
                                            color: colorMap.get(employee.id),
                                          }
                                        : null
                                    }
                                    canEdit={isOffice}
                                    emptyLabel={t("staff.drop_employee_here")}
                                    ariaLabel={cellAriaLabel}
                                    removeAriaLabelFor={(label) =>
                                      t("staff.remove_employee", {
                                        employee: label,
                                      })
                                    }
                                  />
                                </td>
                              );
                            })}
                          </tr>
                        ),
                      )}
                    </tbody>
                  ))}
                </table>
              </section>
            </div>
          )}

          {isFetching && !grid && (
            <p className="text-muted">{t("common.loading")}</p>
          )}
        </div>
      </DndGrid>
    </>
  );
}
