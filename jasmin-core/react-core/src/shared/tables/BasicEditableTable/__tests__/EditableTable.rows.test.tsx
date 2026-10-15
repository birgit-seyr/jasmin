import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { flushMicrotasks, profileRenders } from "@/test/profileRenders";

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

// Switched per test: the phone layout renders cards instead of the table.
const viewport = vi.hoisted(() => ({ mobile: false }));
vi.mock("@hooks/index", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@hooks/index")>()),
  useIsMobile: () => viewport.mobile,
}));

vi.mock("@hooks/configuration/useTenant", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock();
  return { useTenant: () => tenant };
});

import { permissionsWithDeletable } from "../../tablePermissions";
import EditableTable from "../EditableTable";
import type { EditableColumnConfig, TableRecord } from "../types";

type Row = TableRecord & { name: string; crate?: string };

// The rows a page's list query holds; a save doesn't refetch them.
const CARROTS: Row = { key: "1", id: "1", name: "Carrots" };
const LEEKS: Row = { key: "2", id: "2", name: "Leeks" };
const ROWS = [CARROTS, LEEKS];

const NAME_COLUMN: EditableColumnConfig<Row> = {
  title: "Name",
  dataIndex: "name",
  inputType: "text",
  editable: true,
};
const PERMISSIONS = { canAdd: true, canEdit: true, canDelete: true };

const savingApi = () => ({
  create: vi.fn((data: Record<string, unknown>) =>
    Promise.resolve({ data: { ...data, id: "new" } }),
  ),
  update: vi.fn((id: string, data: Record<string, unknown>) =>
    Promise.resolve({ data: { ...data, id } }),
  ),
  delete: vi.fn(() => Promise.resolve({})),
});

async function renameCarrotsTo(name: string) {
  await userEvent.click(
    (await screen.findAllByRole("button", { name: "table.edit" }))[0],
  );
  const input = await screen.findByDisplayValue("Carrots");
  await userEvent.clear(input);
  await userEvent.type(input, name);
  await userEvent.click(screen.getByRole("button", { name: "table.save" }));
  await screen.findByText(name);
}

describe("EditableTable rows after a save", () => {
  it("keeps the saved values when the page renders a new column set", async () => {
    const api = savingApi();
    const { rerender } = render(
      <EditableTable<Row>
        columns={[{ ...NAME_COLUMN }]}
        initialData={ROWS}
        permissions={PERMISSIONS}
        apiFunctions={api}
      />,
    );

    await renameCarrotsTo("Parsnips");
    rerender(
      <EditableTable<Row>
        columns={[{ ...NAME_COLUMN }]}
        initialData={ROWS}
        permissions={PERMISSIONS}
        apiFunctions={api}
      />,
    );
    await flushMicrotasks();

    expect(screen.getByText("Parsnips")).toBeInTheDocument();
    expect(screen.queryByText("Carrots")).not.toBeInTheDocument();
  });

  it("keeps the saved values when the page hands back the rows from before the save", async () => {
    const api = savingApi();
    const renderRows = (rows: Row[]) => (
      <EditableTable<Row>
        columns={[NAME_COLUMN]}
        initialData={rows}
        permissions={PERMISSIONS}
        apiFunctions={api}
      />
    );
    const { rerender } = render(renderRows(ROWS));

    await renameCarrotsTo("Parsnips");
    // A filter toggled off and on again over the unrefetched list.
    rerender(renderRows([LEEKS]));
    await flushMicrotasks();
    rerender(renderRows(ROWS));
    await flushMicrotasks();

    expect(screen.getByText("Parsnips")).toBeInTheDocument();
    expect(screen.queryByText("Carrots")).not.toBeInTheDocument();
  });

  it("sends the saved values with the next edit of the row", async () => {
    const api = savingApi();
    const { rerender } = render(
      <EditableTable<Row>
        columns={[{ ...NAME_COLUMN }]}
        initialData={ROWS}
        permissions={PERMISSIONS}
        apiFunctions={api}
      />,
    );
    await renameCarrotsTo("Parsnips");
    rerender(
      <EditableTable<Row>
        columns={[{ ...NAME_COLUMN }]}
        initialData={ROWS}
        permissions={PERMISSIONS}
        apiFunctions={api}
      />,
    );

    await userEvent.click(
      (await screen.findAllByRole("button", { name: "table.edit" }))[0],
    );

    expect(await screen.findByDisplayValue("Parsnips")).toBeInTheDocument();
  });

  it("shows a refetched row instead of the saved one", async () => {
    const api = savingApi();
    const renderRows = (rows: Row[]) => (
      <EditableTable<Row>
        columns={[NAME_COLUMN]}
        initialData={rows}
        permissions={PERMISSIONS}
        apiFunctions={api}
      />
    );
    const { rerender } = render(renderRows(ROWS));

    await renameCarrotsTo("Parsnips");
    rerender(renderRows([{ ...CARROTS, name: "Turnips" }, LEEKS]));

    expect(await screen.findByText("Turnips")).toBeInTheDocument();
    expect(screen.queryByText("Parsnips")).not.toBeInTheDocument();
  });

  it("takes a field the page patches into its copy and keeps the saved values for the rest", async () => {
    // A login change patched into the page's cached row, which still holds the
    // values from before the save.
    const api = savingApi();
    const columns: EditableColumnConfig<Row>[] = [
      NAME_COLUMN,
      { title: "Login", dataIndex: "login", inputType: "text", disabled: true },
    ];
    const renderRows = (rows: Row[]) => (
      <EditableTable<Row>
        columns={columns}
        initialData={rows}
        permissions={PERMISSIONS}
        apiFunctions={api}
      />
    );
    const { rerender } = render(renderRows(ROWS));

    await renameCarrotsTo("Parsnips");
    rerender(renderRows([{ ...CARROTS, login: "inactive" }, LEEKS]));

    expect(await screen.findByText("inactive")).toBeInTheDocument();
    expect(screen.getByText("Parsnips")).toBeInTheDocument();
    expect(screen.queryByText("Carrots")).not.toBeInTheDocument();
    await userEvent.click(
      (await screen.findAllByRole("button", { name: "table.edit" }))[0],
    );
    expect(await screen.findByDisplayValue("Parsnips")).toBeInTheDocument();
  });
});

describe("EditableTable rows", () => {
  it("shows a select's labels once its options arrive after the rows", async () => {
    const crateColumn = (
      options: { value: string; label: string }[],
    ): EditableColumnConfig<Row> => ({
      title: "Crate",
      dataIndex: "crate_name",
      inputType: "select",
      editable: true,
      foreignKey: { valueField: "crate", displayField: "crate_name" },
      options,
    });
    const rows: Row[] = [{ key: "1", id: "1", name: "Carrots", crate: "c1" }];
    const { rerender } = render(
      <EditableTable<Row>
        columns={[NAME_COLUMN, crateColumn([])]}
        initialData={rows}
        permissions={PERMISSIONS}
        apiFunctions={savingApi()}
      />,
    );
    await screen.findByText("Carrots");
    expect(screen.queryByText("Crate A")).not.toBeInTheDocument();

    rerender(
      <EditableTable<Row>
        columns={[NAME_COLUMN, crateColumn([{ value: "c1", label: "Crate A" }])]}
        initialData={rows}
        permissions={PERMISSIONS}
        apiFunctions={savingApi()}
      />,
    );

    expect(await screen.findByText("Crate A")).toBeInTheDocument();
  });

  it("settles when it loads its own rows without initialData", async () => {
    const profiler = profileRenders();
    // A render loop would never settle; stopping it at a bound turns the hang
    // into a failure.
    profiler.onRender.mockImplementation(() => {
      if (profiler.onRender.mock.calls.length > 200) {
        throw new Error("EditableTable keeps rendering");
      }
    });
    render(
      profiler.wrap(
        <EditableTable<Row>
          columns={[NAME_COLUMN]}
          showSearchBar
          permissions={PERMISSIONS}
          apiFunctions={{
            ...savingApi(),
            list: () => Promise.resolve({ data: [CARROTS] }),
          }}
        />,
      ),
    );

    expect(await screen.findByText("Carrots")).toBeInTheDocument();
    await flushMicrotasks();
    expect(profiler.onRender.mock.calls.length).toBeLessThan(50);
  });

  it("shows why the server refused a delete and keeps the row", async () => {
    const api = {
      ...savingApi(),
      delete: vi.fn(() =>
        Promise.reject({
          isAxiosError: true,
          response: { data: { message: "Still used by an order." } },
        }),
      ),
    };
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <EditableTable<Row>
        columns={[NAME_COLUMN]}
        initialData={ROWS}
        permissions={PERMISSIONS}
        apiFunctions={api}
      />,
    );

    await userEvent.click(
      (await screen.findAllByRole("button", { name: "table.delete" }))[0],
    );
    await userEvent.click(await screen.findByRole("button", { name: "table.yes" }));

    const banner = await screen.findByRole("alert");
    expect(within(banner).getByText("table.delete_failed_title")).toBeInTheDocument();
    expect(within(banner).getByText("Still used by an order.")).toBeInTheDocument();
    expect(screen.getByText("Carrots")).toBeInTheDocument();
  });

  describe("a row whose save the server refuses", () => {
    const refusingApi = () => ({
      ...savingApi(),
      update: vi.fn(() =>
        Promise.reject({
          isAxiosError: true,
          response: { data: { message: "Orders moved the stock." } },
        }),
      ),
    });

    async function renameCarrotsUnsaved(api: ReturnType<typeof refusingApi>) {
      vi.spyOn(console, "error").mockImplementation(() => {});
      render(
        <EditableTable<Row>
          columns={[NAME_COLUMN]}
          initialData={ROWS}
          permissions={PERMISSIONS}
          apiFunctions={api}
        />,
      );
      await userEvent.click(
        (await screen.findAllByRole("button", { name: "table.edit" }))[0],
      );
      const input = await screen.findByDisplayValue("Carrots");
      await userEvent.clear(input);
      await userEvent.type(input, "Purple carrots");
    }

    it("stays open with the server's reason when the office clicks into another row", async () => {
      const api = refusingApi();
      await renameCarrotsUnsaved(api);

      await userEvent.click(screen.getByText("Leeks"));

      expect(await screen.findByText(/Orders moved the stock\./)).toBeInTheDocument();
      expect(api.update).toHaveBeenCalledTimes(1);
      expect(screen.getByDisplayValue("Purple carrots")).toBeInTheDocument();
      expect(screen.queryByDisplayValue("Leeks")).not.toBeInTheDocument();
    });

    it("stays open with the server's reason when the office adds a row", async () => {
      const api = refusingApi();
      await renameCarrotsUnsaved(api);

      await userEvent.click(screen.getByRole("button", { name: "table.add_record" }));

      expect(await screen.findByText(/Orders moved the stock\./)).toBeInTheDocument();
      expect(screen.getByDisplayValue("Purple carrots")).toBeInTheDocument();
      expect(screen.getAllByRole("textbox")).toHaveLength(1);
    });
  });

  it("saves what customEdit put in the form, also when the rows refetch while it is open", async () => {
    // How a page sends a value as the row opened with it: the offers page
    // sends the available amount it showed, which orders move meanwhile.
    const api = savingApi();
    const keepOpenedName = (record: Row) => ({ ...record, opened_name: record.name });
    const table = (rows: Row[]) => (
      <EditableTable<Row>
        columns={[NAME_COLUMN]}
        initialData={rows}
        permissions={PERMISSIONS}
        apiFunctions={api}
        customEdit={keepOpenedName}
      />
    );
    const { rerender } = render(table(ROWS));
    await userEvent.click(
      (await screen.findAllByRole("button", { name: "table.edit" }))[0],
    );

    rerender(table([{ ...CARROTS, name: "Washed carrots" }, LEEKS]));
    await flushMicrotasks();
    await userEvent.click(screen.getByRole("button", { name: "table.save" }));

    await vi.waitFor(() => expect(api.update).toHaveBeenCalledTimes(1));
    expect(api.update.mock.calls[0][1]).toMatchObject({ opened_name: "Carrots" });
  });

  it("counts a value a row hidden from the table holds as taken", async () => {
    const api = savingApi();
    render(
      <EditableTable<Row>
        columns={[NAME_COLUMN]}
        initialData={[CARROTS]}
        uniqueCheckRows={ROWS}
        uniqueCheck="name"
        uniqueCheckMessage="This name is taken."
        permissions={PERMISSIONS}
        apiFunctions={api}
      />,
    );

    await userEvent.click(
      await screen.findByRole("button", { name: /table\.add_record/ }),
    );
    await userEvent.type(await screen.findByRole("textbox", { name: "Name" }), "Leeks");
    await userEvent.click(screen.getByRole("button", { name: "table.save" }));

    expect(await screen.findAllByText(/This name is taken\./)).not.toHaveLength(0);
    expect(api.create).not.toHaveBeenCalled();
  });

  it("shows no action column to a role that may neither edit nor delete", async () => {
    render(
      <EditableTable<Row>
        columns={[NAME_COLUMN]}
        initialData={ROWS}
        permissions={permissionsWithDeletable(false)}
        apiFunctions={savingApi()}
      />,
    );

    await screen.findByText("Carrots");
    expect(
      screen.queryByRole("columnheader", { name: "table.actions" }),
    ).not.toBeInTheDocument();
  });

  it("names an input after its column title when the title is wrapped", async () => {
    render(
      <EditableTable<Row>
        columns={[{ ...NAME_COLUMN, title: <>Article name</> }]}
        initialData={ROWS}
        permissions={PERMISSIONS}
        apiFunctions={savingApi()}
      />,
    );

    await userEvent.click(
      (await screen.findAllByRole("button", { name: "table.edit" }))[0],
    );

    expect(
      await screen.findByRole("textbox", { name: "Article name" }),
    ).toHaveValue("Carrots");
  });
});

describe("EditableTable on a phone", () => {
  it("searches the cards", async () => {
    viewport.mobile = true;
    try {
      render(
        <EditableTable<Row>
          columns={[NAME_COLUMN]}
          initialData={ROWS}
          showSearchBar
          permissions={PERMISSIONS}
          apiFunctions={savingApi()}
        />,
      );
      expect(await screen.findByText("Leeks")).toBeInTheDocument();

      await userEvent.type(
        screen.getByRole("searchbox", { name: "table.search_placeholder" }),
        "carr",
      );

      expect(screen.getByText("Carrots")).toBeInTheDocument();
      expect(screen.queryByText("Leeks")).not.toBeInTheDocument();
    } finally {
      viewport.mobile = false;
    }
  });
});

