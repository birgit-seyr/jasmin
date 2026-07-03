import { describe, expect, it, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";

// Hoisted mocks — vi.mock factories are hoisted, so any closed-over variable
// must be created via vi.hoisted() to survive the lift.
const { notify, axiosMock, useTenantMock } = vi.hoisted(() => ({
  notify: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
    validationError: vi.fn(),
  },
  axiosMock: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
  useTenantMock: vi.fn(() => ({
    getSetting: (key: string) => (key === "date_format" ? "DD.MM.YYYY" : null),
  })),
}));

vi.mock("@shared/utils", () => ({ notify }));
vi.mock("@shared/services/api", () => ({ default: axiosMock }));
vi.mock("@hooks/configuration/useTenant", () => ({
  useTenant: useTenantMock,
}));
// react-i18next isn't initialised inside vitest — return a tiny stub so the
// hook doesn't log a warning on every render.
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback ?? key,
    i18n: { language: "en", changeLanguage: vi.fn() },
  }),
  // Full react-i18next surface (CLAUDE.md rule): Trans is load-bearing the
  // moment a component rendering <Trans> enters this import graph.
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  // initReactI18next is consumed by `src/i18n/index.ts` (transitively pulled
  // in by apiError.ts → getErrorMessage's code-translation lookup). Provide a
  // no-op plugin shape that satisfies i18next's `.use()` call.
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

import { useEditableTable } from "../useEditableTable";
import type { EditableColumnConfig, TableRecord } from "../types";

interface Row extends TableRecord {
  id: string;
  key: string;
  name: string;
  amount: number;
}

const baseColumns: EditableColumnConfig<Row>[] = [
  { title: "Name", dataIndex: "name", inputType: "text" },
  { title: "Amount", dataIndex: "amount", inputType: "number" },
];

const sampleRow: Row = { id: "r1", key: "r1", name: "Carrots", amount: 5 };

beforeEach(() => {
  Object.values(notify).forEach((fn) => fn.mockReset());
  Object.values(axiosMock).forEach((fn) => fn.mockReset());
});

describe("useEditableTable", () => {
  it("edit() stores the editing key and seeds the form with the record values", async () => {
    const { result } = renderHook(() =>
      useEditableTable<Row>({ columns: baseColumns }),
    );

    act(() => {
      result.current.setDataWithTransform([sampleRow]);
    });

    await act(async () => {
      await result.current.edit(sampleRow);
    });

    expect(result.current.editingKey).toBe("r1");
    expect(result.current.isEditing(sampleRow)).toBe(true);
    // No <Form/> is rendered, so only the internal store has the values —
    // pass `true` to read every field, registered or not.
    expect(result.current.form.getFieldsValue(true)).toMatchObject({
      name: "Carrots",
      amount: 5,
    });
  });

  it("cancel() clears editingKey and removes any unsaved (key=-1) draft row", () => {
    const { result } = renderHook(() =>
      useEditableTable<Row>({ columns: baseColumns }),
    );

    act(() => {
      result.current.setDataWithTransform([
        sampleRow,
        { id: "draft", key: -1, name: "", amount: 0 } as unknown as Row,
      ]);
    });
    expect(result.current.data).toHaveLength(2);

    act(() => {
      result.current.cancel();
    });

    expect(result.current.editingKey).toBe("");
    expect(result.current.data).toEqual([sampleRow]);
    expect(result.current.formErrors).toEqual({});
  });

  it("save() PATCHes via apiFunctions.update and replaces the row in data", async () => {
    const updated: Row = { ...sampleRow, name: "Beets", amount: 9 };
    const apiFunctions = {
      update: vi.fn().mockResolvedValue({ data: updated }),
    };
    const onSaveSuccess = vi.fn();
    const onDataChange = vi.fn();

    const { result } = renderHook(() =>
      useEditableTable<Row>({
        columns: baseColumns,
        apiFunctions,
        onSaveSuccess,
        onDataChange,
      }),
    );

    act(() => {
      result.current.setDataWithTransform([sampleRow]);
    });

    await act(async () => {
      await result.current.save("r1", { name: "Beets", amount: 9 });
    });

    expect(apiFunctions.update).toHaveBeenCalledWith("r1", {
      name: "Beets",
      amount: 9,
    });
    expect(result.current.data[0]).toMatchObject({
      key: "r1",
      name: "Beets",
      amount: 9,
    });
    expect(onSaveSuccess).toHaveBeenCalledWith(updated, "update");
    expect(onDataChange).toHaveBeenCalled();
  });

  it("save() POSTs via apiFunctions.create when the row is the (key=-1) draft", async () => {
    const created: Row = { id: "new1", key: "new1", name: "Kale", amount: 3 };
    const apiFunctions = {
      create: vi.fn().mockResolvedValue({ data: created }),
    };
    const onSaveSuccess = vi.fn();

    const { result } = renderHook(() =>
      useEditableTable<Row>({
        columns: baseColumns,
        apiFunctions,
        onSaveSuccess,
      }),
    );

    act(() => {
      result.current.setDataWithTransform([
        { id: "draft", key: -1, name: "", amount: 0 } as unknown as Row,
      ]);
    });

    await act(async () => {
      await result.current.save(-1, { name: "Kale", amount: 3 });
    });

    expect(apiFunctions.create).toHaveBeenCalledWith({
      name: "Kale",
      amount: 3,
    });
    // Draft row should be replaced by the server response, keyed by id.
    expect(result.current.data[0]).toMatchObject({
      key: "new1",
      name: "Kale",
      amount: 3,
    });
    expect(onSaveSuccess).toHaveBeenCalledWith(created, "create");
  });

  it("customSave returning null aborts the save without hitting the API", async () => {
    const apiFunctions = { update: vi.fn() };
    const customSave = vi.fn(() => null);

    const { result } = renderHook(() =>
      useEditableTable<Row>({
        columns: baseColumns,
        apiFunctions,
        customSave,
      }),
    );

    act(() => {
      result.current.setDataWithTransform([sampleRow]);
    });

    await act(async () => {
      await result.current.save("r1", { name: "X", amount: 1 });
    });

    expect(customSave).toHaveBeenCalled();
    expect(apiFunctions.update).not.toHaveBeenCalled();
  });

  it("customSave returning the __deleteOnSave sentinel deletes the row instead of updating", async () => {
    // Regression: clearing an order's amount removes the OrderContent (offers
    // with no order are placeholder stubs, not null-amount rows). The offers
    // customSave returns { __deleteOnSave: true } for a cleared EXISTING row;
    // the save handler must route that to apiFunctions.delete + remove the
    // row, NOT to update. Covers the "works with 0 but not with an empty
    // field" case — here the value is empty ("").
    const apiFunctions = {
      update: vi.fn(),
      delete: vi.fn().mockResolvedValue(undefined),
    };
    const onDeleteSuccess = vi.fn();
    const customSave = vi.fn(() => ({ __deleteOnSave: true }));

    const { result } = renderHook(() =>
      useEditableTable<Row>({
        columns: baseColumns,
        apiFunctions,
        customSave,
        onDeleteSuccess,
      }),
    );

    act(() => {
      result.current.setDataWithTransform([sampleRow]);
    });

    await act(async () => {
      // Empty amount — the user cleared the field rather than typing 0.
      await result.current.save("r1", { name: "Carrots", amount: "" });
    });

    expect(customSave).toHaveBeenCalled();
    expect(apiFunctions.update).not.toHaveBeenCalled();
    expect(apiFunctions.delete).toHaveBeenCalledWith("r1");
    expect(onDeleteSuccess).toHaveBeenCalledWith("r1");
    expect(result.current.data.find((r) => r.key === "r1")).toBeUndefined();
  });

  it("uniqueCheck blocks the save when another row already has the same value", async () => {
    const apiFunctions = { update: vi.fn() };

    const { result } = renderHook(() =>
      useEditableTable<Row>({
        columns: baseColumns,
        apiFunctions,
        uniqueCheck: "name",
        uniqueCheckMessage: "Name must be unique",
      }),
    );

    act(() => {
      result.current.setDataWithTransform([
        sampleRow,
        { id: "r2", key: "r2", name: "Beets", amount: 1 },
      ]);
    });

    await act(async () => {
      await result.current.save("r1", { name: "Beets", amount: 5 });
    });

    expect(apiFunctions.update).not.toHaveBeenCalled();
    // Unique-check failures now surface in the table banner (saveErrorMessage)
    // instead of a fleeting toast. The red border still comes from formErrors.
    await waitFor(() => {
      expect(result.current.saveErrorMessage).toBe("Name must be unique");
    });
    expect(result.current.formErrors.name).toBe("Name must be unique");
  });

  it("save() captures server-side field errors into formErrors when the API rejects", async () => {
    const apiFunctions = {
      update: vi.fn().mockRejectedValue({
        isAxiosError: true,
        response: { data: { name: "already taken" } },
      }),
    };

    const { result } = renderHook(() =>
      useEditableTable<Row>({ columns: baseColumns, apiFunctions }),
    );

    act(() => {
      result.current.setDataWithTransform([sampleRow]);
    });
    await act(async () => {
      await result.current.edit(sampleRow);
    });

    await act(async () => {
      await result.current.save("r1", { name: "Dup", amount: 5 });
    });

    await waitFor(() => {
      expect(result.current.formErrors).toEqual({ name: "already taken" });
    });
    // Save errors keep the row in edit mode so the user can retry.
    expect(result.current.editingKey).toBe("r1");
  });

  it("add() inserts a (key=-1) draft row at the top and switches to edit mode on it", async () => {
    const { result } = renderHook(() =>
      useEditableTable<Row>({ columns: baseColumns }),
    );

    act(() => {
      result.current.setDataWithTransform([sampleRow]);
    });

    await act(async () => {
      await result.current.add();
    });

    expect(result.current.data[0].key).toBe(-1);
    expect(result.current.data).toHaveLength(2);
    expect(result.current.editingKey).toBe(-1);
  });

  it("deleteRecord() calls apiFunctions.delete and removes the row from data", async () => {
    const apiFunctions = { delete: vi.fn().mockResolvedValue({}) };
    const onDeleteSuccess = vi.fn();

    const { result } = renderHook(() =>
      useEditableTable<Row>({
        columns: baseColumns,
        apiFunctions,
        onDeleteSuccess,
      }),
    );

    act(() => {
      result.current.setDataWithTransform([
        sampleRow,
        { id: "r2", key: "r2", name: "Beets", amount: 1 },
      ]);
    });

    await act(async () => {
      await result.current.deleteRecord("r1");
    });

    expect(apiFunctions.delete).toHaveBeenCalledWith("r1");
    expect(result.current.data).toEqual([
      { id: "r2", key: "r2", name: "Beets", amount: 1 },
    ]);
    expect(onDeleteSuccess).toHaveBeenCalledWith("r1");
  });

  it("deleteRecord() rethrows when the API rejects so the caller can show feedback", async () => {
    const apiFunctions = {
      delete: vi.fn().mockRejectedValue(new Error("boom")),
    };
    // deleteRecord logs the error before rethrowing — silence noise.
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    const { result } = renderHook(() =>
      useEditableTable<Row>({ columns: baseColumns, apiFunctions }),
    );

    act(() => {
      result.current.setDataWithTransform([sampleRow]);
    });

    await expect(
      act(async () => {
        await result.current.deleteRecord("r1");
      }),
    ).rejects.toThrow("boom");

    // Row stayed in data because the delete failed.
    expect(result.current.data).toEqual([sampleRow]);
    errSpy.mockRestore();
  });
});
