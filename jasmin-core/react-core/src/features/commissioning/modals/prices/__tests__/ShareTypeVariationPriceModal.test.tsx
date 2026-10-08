/**
 * Column-gating test for ``ShareTypeVariationPriceModal``.
 *
 * The ``solidarity_min_price_per_delivery`` column is spread into the price
 * grid ONLY when ``allows_solidarity_pricing`` is on. This pins that gate.
 *
 * Strategy: stub ``PriceEditorModal`` (the generic shell that renders the real
 * AntD ``EditableTable`` — which hangs vitest, see the project note) so we can
 * capture the ``columns`` prop the modal builds and assert on its shape WITHOUT
 * mounting a table. Every hook the modal reads is mocked at the ``@hooks/index``
 * boundary; ``useTenant().getSetting`` is the toggle under test.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import type { EditableColumnConfig } from "@shared/tables/BasicEditableTable/types";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

// ── Tenant setting toggle (the thing under test) ───────────────────────────
const getSettingMock = vi.fn();
vi.mock("@hooks/index", () => ({
  useTenant: () => ({ getSetting: getSettingMock, refreshTenant: vi.fn() }),
  useCurrency: () => ({ currencySymbol: "€" }),
  // Only its `shares` rate is read, and only to forward as a prop to the
  // stubbed editor shell — the value is irrelevant to the column assertions.
  useDefaultTaxRates: () => ({ shares: 7 }),
  // Column hooks return inert column stubs — their concrete shape is
  // irrelevant to this test, which only inspects the solidarity column.
  useActiveStatusColumn: () => ({ key: "active", dataIndex: "active" }),
  useTimeBoundColumns: () => ({
    validFromColumn: { key: "valid_from", dataIndex: "valid_from" },
    validUntilColumn: { key: "valid_until", dataIndex: "valid_until" },
  }),
}));

// Generated API fns referenced only as props on the shell — inert stubs.
vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  commissioningShareTypeVariationPriceCreate: vi.fn(),
  commissioningShareTypeVariationPriceDestroy: vi.fn(),
  commissioningShareTypeVariationPricePartialUpdate: vi.fn(),
  getCommissioningShareTypeVariationPriceListQueryKey: vi.fn(),
  useCommissioningShareTypeVariationPriceList: vi.fn(),
}));

// The solidarity toggle persists via this mutation hook — stub it so the modal
// renders without a QueryClientProvider (columns are the thing under test).
vi.mock("@shared/api/generated/tenants/tenants", () => ({
  useTenantsSettingsUpdateCurrentSettingsUpdate: () => ({
    mutate: vi.fn(),
    isPending: false,
  }),
}));

vi.mock("@shared/ui", () => ({
  ToolTipIcon: () => null,
}));

// ── Capture the columns the modal hands the (stubbed) editor shell ─────────
let capturedColumns: EditableColumnConfig[] = [];
let capturedProps: { onSave?: () => void; api?: unknown }[] = [];
vi.mock("../PriceEditorModal", () => ({
  default: (props: {
    columns: EditableColumnConfig[];
    onSave?: () => void;
    api?: unknown;
  }) => {
    capturedColumns = props.columns;
    capturedProps.push(props);
    return <div data-testid="price-editor-shell" />;
  },
}));

import ShareTypeVariationPriceModal from "../ShareTypeVariationPriceModal";

const SOLIDARITY_COL = "solidarity_min_price_per_delivery";

function modal(onSave?: () => void): ReactElement {
  return (
    <ShareTypeVariationPriceModal
      visible
      onClose={vi.fn()}
      onSave={onSave}
      share_type_variation="stv-1"
      share_type_variation_name="Gemüse M"
    />
  );
}

function renderModal(onSave?: () => void) {
  return render(modal(onSave));
}

beforeEach(() => {
  capturedColumns = [];
  capturedProps = [];
  getSettingMock.mockReset();
});

describe("ShareTypeVariationPriceModal — solidarity column gating", () => {
  it("includes the solidarity_min column when allows_solidarity_pricing is ON", () => {
    getSettingMock.mockImplementation((key: string) =>
      key === "allows_solidarity_pricing" ? true : undefined,
    );

    renderModal();

    const dataIndexes = capturedColumns.map((c) => c.dataIndex);
    expect(dataIndexes).toContain(SOLIDARITY_COL);
    // The reference price column is always present, regardless of the toggle.
    expect(dataIndexes).toContain("price_per_delivery");
  });

  it("omits the solidarity_min column when allows_solidarity_pricing is OFF", () => {
    getSettingMock.mockImplementation((key: string, fallback?: unknown) =>
      // Mirror the component's getSetting(key, false) default.
      key === "allows_solidarity_pricing" ? false : fallback,
    );

    renderModal();

    const dataIndexes = capturedColumns.map((c) => c.dataIndex);
    expect(dataIndexes).not.toContain(SOLIDARITY_COL);
    // The reference price column survives the toggle being off.
    expect(dataIndexes).toContain("price_per_delivery");
  });
});

describe("ShareTypeVariationPriceModal — editor wiring", () => {
  it("hands the caller's onSave to the editor, so the variation list reloads after a price change", () => {
    const onSave = vi.fn();

    renderModal(onSave);

    expect(capturedProps.at(-1)?.onSave).toBe(onSave);
  });

  it("keeps the editor's API functions the same object across renders", () => {
    const { rerender } = renderModal();
    rerender(modal());

    expect(capturedProps.length).toBeGreaterThan(1);
    expect(capturedProps.at(-1)?.api).toBe(capturedProps[0].api);
  });
});
