import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CrudResource } from "../useCrudListPage";
import type {
  EditableColumnConfig,
  TableRecord,
} from "../BasicEditableTable/types";

// Capture the props CrudListPage hands to EditableTable (hoisted so the mock
// factory can reference it safely — see CLAUDE.md test conventions).
const captured = vi.hoisted(() => ({ props: null as Record<string, unknown> | null }));

vi.mock("../BasicEditableTable", () => ({
  default: (props: Record<string, unknown>) => {
    captured.props = props;
    return <div data-testid="editable-table" />;
  },
}));

vi.mock("@shared/ui", () => ({
  HideInactiveSwitch: ({
    value,
    onChange,
  }: {
    value: boolean;
    onChange: (v: boolean) => void;
  }) => (
    <button
      data-testid="hide-inactive"
      data-value={String(value)}
      onClick={() => onChange(!value)}
    />
  ),
  ExplainerText: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="explainer">{children}</div>
  ),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

// Imported after the mocks are declared (vi.mock is hoisted regardless).
import { CrudListPage } from "../CrudListPage";

type Row = TableRecord & { name?: string; is_active?: boolean };

const ROWS: Row[] = [
  { key: "1", id: "1", name: "Active", is_active: true },
  { key: "2", id: "2", name: "Inactive", is_active: false },
];

const resource: CrudResource<Row> = {
  useList: () => ({ data: ROWS, isLoading: false, isFetching: false }),
  create: vi.fn().mockResolvedValue({}),
  update: vi.fn().mockResolvedValue({}),
  delete: vi.fn().mockResolvedValue({}),
  getListQueryKey: () => ["storages"] as const,
};

function renderPage(extra: Record<string, unknown> = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <CrudListPage<Row>
        titleKey="title"
        resource={resource}
        permissions={{ canAdd: true, canEdit: true, canDelete: true }}
        columns={[] as EditableColumnConfig<Row>[]}
        {...extra}
      />
    </QueryClientProvider>,
  );
}

function tableProps() {
  if (!captured.props) throw new Error("EditableTable never rendered");
  return captured.props;
}

describe("CrudListPage", () => {
  beforeEach(() => {
    captured.props = null;
  });

  it("hides inactive rows by default, shows all when the switch is toggled", () => {
    renderPage();
    expect((tableProps().initialData as Row[]).map((r) => r.name)).toEqual([
      "Active",
    ]);

    fireEvent.click(screen.getByTestId("hide-inactive"));
    expect((tableProps().initialData as Row[]).map((r) => r.name)).toEqual([
      "Active",
      "Inactive",
    ]);
  });

  it("owns the data: apiFunctions expose CRUD but NO list (no double fetch)", () => {
    renderPage();
    const api = tableProps().apiFunctions as Record<string, unknown>;
    expect(typeof api.create).toBe("function");
    expect(typeof api.update).toBe("function");
    expect(typeof api.delete).toBe("function");
    expect(api.list).toBeUndefined();
  });

  it("customEdit stamps the new-row defaults on the key === -1 draft only", () => {
    renderPage();
    const customEdit = tableProps().customEdit as (
      record: Row,
      form: { setFieldsValue: (v: Record<string, unknown>) => void },
    ) => Row;

    const setFieldsValue = vi.fn();
    const created = customEdit({ key: -1 } as Row, { setFieldsValue });
    expect(setFieldsValue).toHaveBeenCalledWith({ is_active: true });
    expect(created.is_active).toBe(true);

    const existing: Row = { key: "1", id: "1", is_active: false };
    expect(customEdit(existing, { setFieldsValue })).toBe(existing);
  });

  it("withHideInactive=false renders no switch and applies no filter", () => {
    renderPage({ withHideInactive: false });
    expect(screen.queryByTestId("hide-inactive")).toBeNull();
    expect((tableProps().initialData as Row[]).map((r) => r.name)).toEqual([
      "Active",
      "Inactive",
    ]);
  });
});
