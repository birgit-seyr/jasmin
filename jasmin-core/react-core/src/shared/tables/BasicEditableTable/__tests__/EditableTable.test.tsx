import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { axe } from "@/test/axe";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

// Inline editing, the mode a new user starts in.
vi.mock("@shared/contexts/ModalContext", () => ({
  useModal: () => ({ isModalMode: false }),
}));

vi.mock("@hooks/configuration/useTenant", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock();
  return { useTenant: () => tenant };
});

import EditableTable from "../EditableTable";
import type { EditableColumnConfig, TableRecord } from "../types";

type Row = TableRecord & { name: string; amount: number };

const ROWS: Row[] = [
  { key: "1", id: "1", name: "Carrots", amount: 3 },
  { key: "2", id: "2", name: "Leeks", amount: 5 },
];

const COLUMNS: EditableColumnConfig<Row>[] = [
  { title: "Name", dataIndex: "name", inputType: "text", editable: true },
  { title: "Amount", dataIndex: "amount", inputType: "number", editable: true },
];

function renderTable() {
  return render(
    <EditableTable<Row>
      columns={COLUMNS}
      initialData={ROWS}
      permissions={{ canAdd: true, canEdit: true, canDelete: true }}
      apiFunctions={{
        create: vi.fn(),
        update: vi.fn(),
        delete: vi.fn(),
      }}
    />,
  );
}

describe("EditableTable", () => {
  it("names every column, including the actions column", async () => {
    const { container } = renderTable();

    expect(await screen.findByText("Carrots")).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: "table.actions" }),
    ).toBeInTheDocument();
    expect(await axe(container)).toHaveNoViolations();
  });

  it("labels the inputs of a row being edited inline", async () => {
    const { container } = renderTable();

    await userEvent.click(
      (await screen.findAllByRole("button", { name: "table.edit" }))[0],
    );

    // The first cell takes focus a frame later, ready to be typed over.
    const nameInput = await screen.findByDisplayValue("Carrots");
    await waitFor(() => expect(nameInput).toHaveFocus());
    expect(await axe(container)).toHaveNoViolations();
  });
});

describe("EditableTable select search", () => {
  // Options may carry formatted labels — a weekday with a status dot and its
  // dates, say; the search reads their text.
  const dayColumns: EditableColumnConfig<TableRecord>[] = [
    {
      title: "Day",
      dataIndex: "day",
      inputType: "select",
      editable: true,
      options: [
        {
          value: "tue",
          label: (
            <span>
              <span className="status-dot" />
              Tuesday <span>from 05.01.2026</span>
            </span>
          ) as unknown as string,
        },
        { value: "thu", label: "Thursday" },
      ],
    },
  ];

  it("filters options with formatted labels by their text", async () => {
    render(
      <EditableTable<TableRecord>
        columns={dayColumns}
        initialData={[{ key: "1", id: "1", day: "thu" }]}
        permissions={{ canAdd: true, canEdit: true, canDelete: true }}
        apiFunctions={{ create: vi.fn(), update: vi.fn(), delete: vi.fn() }}
      />,
    );
    await userEvent.click(
      (await screen.findAllByRole("button", { name: "table.edit" }))[0],
    );

    await userEvent.type(screen.getByRole("combobox", { name: "Day" }), "tues");

    const offered = await waitFor(() => {
      const options = Array.from(
        document.querySelectorAll(
          ".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option",
        ),
      );
      if (options.length === 0) throw new Error("No options are offered");
      return options;
    });
    expect(offered.map((option) => option.textContent)).toEqual([
      "Tuesday from 05.01.2026",
    ]);
  });
});

describe("EditableTable cell errors for screen readers", () => {
  const requiredColumns: EditableColumnConfig<Row>[] = [
    { title: "Name", dataIndex: "name", inputType: "text", editable: true, required: true },
    { title: "Amount", dataIndex: "amount", inputType: "number", editable: true },
  ];

  async function editCarrots(columns: EditableColumnConfig<Row>[], uniqueCheck?: string) {
    render(
      <EditableTable<Row>
        columns={columns}
        initialData={ROWS}
        permissions={{ canAdd: true, canEdit: true, canDelete: true }}
        apiFunctions={{ create: vi.fn(), update: vi.fn(), delete: vi.fn() }}
        uniqueCheck={uniqueCheck}
        uniqueCheckMessage="This name is taken"
      />,
    );
    await userEvent.click((await screen.findAllByRole("button", { name: "table.edit" }))[0]);
    return screen.getByRole("textbox", { name: "Name" });
  }

  it("describes an emptied required cell by its required error", async () => {
    const nameInput = await editCarrots(requiredColumns);

    await userEvent.clear(nameInput);
    await userEvent.click(screen.getByRole("button", { name: "table.save" }));

    await waitFor(() => expect(nameInput).toHaveAccessibleDescription("table.required"));
    expect(nameInput).toBeInvalid();
  });

  it("describes a cell the table refused by the table's own reason", async () => {
    const nameInput = await editCarrots(COLUMNS, "name");

    await userEvent.clear(nameInput);
    await userEvent.type(nameInput, "Leeks");
    await userEvent.click(screen.getByRole("button", { name: "table.save" }));

    await waitFor(() => expect(nameInput).toHaveAccessibleDescription("This name is taken"));
    expect(nameInput).toBeInvalid();
  });

  it("describes a valid cell by nothing", async () => {
    const nameInput = await editCarrots(requiredColumns);

    expect(nameInput).toHaveAccessibleDescription("");
    expect(nameInput).toBeValid();
  });
});
