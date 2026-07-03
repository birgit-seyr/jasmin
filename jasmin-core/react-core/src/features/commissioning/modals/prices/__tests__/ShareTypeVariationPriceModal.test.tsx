/**
 * Column-gating test for ``ShareTypeVariationPriceModal``.
 *
 * The solidarity-pricing audit (SOL-9/SOL-10) flagged that the
 * ``solidarity_min_price_per_delivery`` column is spread into the price grid
 * ONLY when ``allows_solidarity_pricing`` is on — and that this gate had zero
 * coverage. This pins it.
 *
 * Strategy: stub ``PriceEditorModal`` (the generic shell that renders the real
 * AntD ``EditableTable`` — which hangs vitest, see the project note) so we can
 * capture the ``columns`` prop the modal builds and assert on its shape WITHOUT
 * mounting a table. Every hook the modal reads is mocked at the ``@hooks/index``
 * boundary; ``useTenant().getSetting`` is the toggle under test.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render } from "@testing-library/react";
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
  useTenant: () => ({ getSetting: getSettingMock }),
  useCurrency: () => ({ currencySymbol: "€" }),
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

vi.mock("@shared/ui", () => ({
  ToolTipIcon: () => null,
}));

// ── Capture the columns the modal hands the (stubbed) editor shell ─────────
let capturedColumns: EditableColumnConfig[] = [];
vi.mock("../PriceEditorModal", () => ({
  default: (props: { columns: EditableColumnConfig[] }) => {
    capturedColumns = props.columns;
    return <div data-testid="price-editor-shell" />;
  },
}));

import ShareTypeVariationPriceModal from "../ShareTypeVariationPriceModal";

const SOLIDARITY_COL = "solidarity_min_price_per_delivery";

function renderModal() {
  render(
    <ShareTypeVariationPriceModal
      visible
      onClose={vi.fn()}
      share_type_variation="stv-1"
      share_type_variation_name="Gemüse M"
    />,
  );
}

beforeEach(() => {
  capturedColumns = [];
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
