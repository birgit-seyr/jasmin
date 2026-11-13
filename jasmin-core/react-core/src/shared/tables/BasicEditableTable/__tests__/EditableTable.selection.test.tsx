/**
 * EditableTable's ticked rows when the page holds the selection, the way
 * `useTableRowSelection` does: what the checkboxes show, and what the page — and
 * so its bulk actions — is told when rows are unticked, hidden or replaced.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Key } from "react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { flushMicrotasks } from "@/test/profileRenders";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

vi.mock("@shared/contexts/ModalContext", () => ({
  useModal: () => ({ isModalMode: false }),
}));

vi.mock("@hooks/configuration/useTenant", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock();
  return { useTenant: () => tenant };
});

import { useTableRowSelection } from "@shared/hooks/useTableRowSelection";
import EditableTable from "../EditableTable";
import type { EditableColumnConfig, TableRecord } from "../types";

type Row = TableRecord & { name: string };

const CARROTS: Row = { key: "1", id: "1", name: "Carrots" };
const LEEKS: Row = { key: "2", id: "2", name: "Leeks" };
const ONIONS: Row = { key: "3", id: "3", name: "Onions" };

const NAME_COLUMN: EditableColumnConfig<Row> = {
  title: "Name",
  dataIndex: "name",
  inputType: "text",
};
const READ_ONLY = { canAdd: false, canEdit: false, canDelete: false };

/** A page holding the selection, with the ids its bulk actions would send. */
function Page({ rows, week = "41" }: { rows: Row[]; week?: string }) {
  const [selected, setSelected] = useState<Key[]>([]);
  return (
    <>
      <output aria-label="bulk action ids">{selected.join(",")}</output>
      <EditableTable<Row>
        key={week}
        columns={[NAME_COLUMN]}
        initialData={rows}
        permissions={READ_ONLY}
        rowSelection={{ type: "checkbox" }}
        selectedRowKeys={selected}
        onSelectedRowsChange={setSelected}
      />
    </>
  );
}

const bulkActionIds = () =>
  screen.getByRole("status", { name: "bulk action ids" }).textContent;
const checkboxOf = (name: string) =>
  within(screen.getByText(name).closest("tr") as HTMLElement).getByRole(
    "checkbox",
  );
const selectAll = () => screen.getAllByRole("checkbox")[0];

describe("EditableTable row selection held by the page", () => {
  it("shows no tick once the last ticked row is unticked, and then selects only the next one", async () => {
    render(<Page rows={[CARROTS, LEEKS]} />);
    await userEvent.click(checkboxOf("Carrots"));
    expect(bulkActionIds()).toBe("1");

    await userEvent.click(checkboxOf("Carrots"));

    expect(bulkActionIds()).toBe("");
    expect(checkboxOf("Carrots")).not.toBeChecked();

    await userEvent.click(checkboxOf("Leeks"));

    expect(bulkActionIds()).toBe("2");
    expect(checkboxOf("Carrots")).not.toBeChecked();
  });

  it("shows no tick after everything is deselected", async () => {
    render(<Page rows={[CARROTS, LEEKS]} />);
    await userEvent.click(selectAll());
    expect(bulkActionIds()).toBe("1,2");

    await userEvent.click(selectAll());

    expect(bulkActionIds()).toBe("");
    expect(checkboxOf("Carrots")).not.toBeChecked();
    expect(checkboxOf("Leeks")).not.toBeChecked();
  });

  it("drops a ticked row the page no longer lists and tells the page", async () => {
    const { rerender } = render(<Page rows={[CARROTS, LEEKS, ONIONS]} />);
    await userEvent.click(checkboxOf("Carrots"));
    await userEvent.click(checkboxOf("Onions"));
    expect(bulkActionIds()).toBe("1,3");

    // A filter hides the carrots.
    rerender(<Page rows={[LEEKS, ONIONS]} />);

    await waitFor(() => expect(bulkActionIds()).toBe("3"));
    expect(checkboxOf("Onions")).toBeChecked();
  });

  it("starts another week's table with nothing ticked", async () => {
    const { rerender } = render(<Page rows={[CARROTS, LEEKS]} week="41" />);
    await userEvent.click(checkboxOf("Carrots"));
    expect(bulkActionIds()).toBe("1");

    rerender(<Page rows={[ONIONS]} week="42" />);

    await waitFor(() => expect(bulkActionIds()).toBe(""));
    expect(checkboxOf("Onions")).not.toBeChecked();
  });

  it("keeps the ticks when the page refetches the same rows", async () => {
    const { rerender } = render(<Page rows={[CARROTS, LEEKS]} />);
    await userEvent.click(checkboxOf("Leeks"));

    rerender(<Page rows={[{ ...CARROTS }, { ...LEEKS }]} />);
    await flushMicrotasks();

    expect(bulkActionIds()).toBe("2");
    expect(checkboxOf("Leeks")).toBeChecked();
  });
});

/** A paginated page whose selection reaches past the visible page; the last
 *  row can't be ticked. */
function PagedPage({ rows }: { rows: Row[] }) {
  const { selectedRowKeys, onSelectedRowsChange, rowSelection } =
    useTableRowSelection<Row>((row) => row.id === "11", { allRows: rows });
  return (
    <>
      <output aria-label="bulk action ids">{selectedRowKeys.join(",")}</output>
      <EditableTable<Row>
        columns={[NAME_COLUMN]}
        initialData={rows}
        permissions={READ_ONLY}
        rowSelection={rowSelection}
        selectedRowKeys={selectedRowKeys}
        onSelectedRowsChange={onSelectedRowsChange}
        pagination={true}
      />
    </>
  );
}

const PEARS: Row[] = Array.from({ length: 12 }, (_, index) => ({
  key: String(index),
  id: String(index),
  name: `Pear ${index}`,
}));

describe("EditableTable row selection across pages", () => {
  it("ticks the visible page from the header, and every page or none from its menu", async () => {
    render(<PagedPage rows={PEARS} />);

    await userEvent.click(selectAll());
    expect(bulkActionIds()).toBe("0,1,2,3,4,5,6,7,8,9");

    await userEvent.hover(
      document.querySelector(".ant-table-selection-extra > span") as HTMLElement,
    );
    await userEvent.click(await screen.findByText("table.select_all_pages"));

    expect(bulkActionIds()).toBe("0,1,2,3,4,5,6,7,8,9,10");
    // The pager sits above and below the table.
    await userEvent.click(screen.getAllByTitle("2")[0]);
    expect(checkboxOf("Pear 10")).toBeChecked();
    expect(checkboxOf("Pear 11")).not.toBeChecked();

    await userEvent.hover(
      document.querySelector(".ant-table-selection-extra > span") as HTMLElement,
    );
    await userEvent.click(await screen.findByText("table.select_none"));

    expect(bulkActionIds()).toBe("");
  });
});

describe("EditableTable row selection held by the table", () => {
  it("keeps its own ticks and reports them when the page holds none", async () => {
    const onSelectedRowsChange = vi.fn();
    render(
      <EditableTable<Row>
        columns={[NAME_COLUMN]}
        initialData={[CARROTS, LEEKS]}
        permissions={READ_ONLY}
        rowSelection={{ type: "checkbox" }}
        onSelectedRowsChange={onSelectedRowsChange}
      />,
    );

    await userEvent.click(checkboxOf("Leeks"));

    expect(checkboxOf("Leeks")).toBeChecked();
    expect(onSelectedRowsChange).toHaveBeenLastCalledWith(
      ["2"],
      [expect.objectContaining({ name: "Leeks" })],
    );
  });
});
