/**
 * VirtualComponentModal: which physical variations of the same share type a
 * virtual variation is packed from, and how many of each. Rendered for real;
 * the generated commissioning client is the mocking boundary, with both list
 * hooks real TanStack queries around spies that answer from an in-memory
 * server. The tenant sets no number format, so the quantity field writes
 * numbers the German way.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  ShareTypeVariation,
  VirtualVariationComponentListItem,
} from "@shared/api/generated/models";
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

vi.mock("@hooks/configuration/useTenant", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock();
  return { useTenant: () => tenant };
});

const notify = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  warning: vi.fn(),
  info: vi.fn(),
}));
vi.mock("@shared/utils/notify", () => ({ default: notify }));

const api = vi.hoisted(() => ({
  listVariations: vi.fn(),
  listComponents: vi.fn(),
  saveComponents: vi.fn(),
}));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  const variationsKey = (params?: unknown) => [
    "/api/commissioning/share_type_variations/",
    ...(params ? [params] : []),
  ];
  const componentsKey = (params?: unknown) => [
    "/api/commissioning/virtual_variation_components/",
    ...(params ? [params] : []),
  ];
  return {
    getCommissioningVirtualVariationComponentsListQueryKey: componentsKey,
    useCommissioningShareTypeVariationsList: (
      params: unknown,
      options?: { query?: { enabled?: boolean } },
    ) =>
      useQuery({
        queryKey: variationsKey(params),
        queryFn: () => api.listVariations(params),
        enabled: options?.query?.enabled,
      }),
    useCommissioningVirtualVariationComponentsList: (
      params: unknown,
      options?: { query?: { enabled?: boolean } },
    ) =>
      useQuery({
        queryKey: componentsKey(params),
        queryFn: () => api.listComponents(params),
        enabled: options?.query?.enabled,
      }),
    commissioningVirtualVariationComponentsCreate: (body: unknown) =>
      api.saveComponents(body),
  };
});

import VirtualComponentModal from "../VirtualComponentModal";

// ── Fixtures ────────────────────────────────────────────────────────────────

function variation(id: string, size: ShareTypeVariation["size"]): ShareTypeVariation {
  return {
    id,
    share_type: "st-veg",
    size,
    valid_from: "2026-01-05",
    valid_until: null,
    variation_type: "physical",
  } as ShareTypeVariation;
}

const SMALL = variation("var-small", "S");
const LARGE = variation("var-large", "L");
// The virtual variation itself; the backend may list it among the physical ones.
const FAMILY = variation("var-family", "XL");

function component(
  physical_variation: string,
  quantity: number,
): VirtualVariationComponentListItem {
  return {
    id: `comp-${physical_variation}`,
    virtual_variation: FAMILY.id!,
    physical_variation,
    physical_variation_name: physical_variation,
    quantity,
  };
}

const SMALL_LABEL = "commissioning.S";
const LARGE_LABEL = "commissioning.L";
const QUANTITY = /^commissioning\.quantity:?$/;
const SAVE = "common.save";
const CANCEL = "common.cancel";

let serverComponents: VirtualVariationComponentListItem[] = [];

beforeEach(() => {
  Object.values(notify).forEach((fn) => fn.mockReset());
  serverComponents = [];
  api.listVariations.mockReset().mockImplementation(async () => [SMALL, LARGE, FAMILY]);
  api.listComponents.mockReset().mockImplementation(async () => [...serverComponents]);
  api.saveComponents.mockReset().mockResolvedValue({
    virtual_variation: FAMILY.id,
    variation_type: "virtual",
    components: [],
  });
});

// ── Helpers ─────────────────────────────────────────────────────────────────

interface RenderOptions {
  visible?: boolean;
  shareType?: string | null;
  variationId?: string | null;
}

function renderModal({
  visible = true,
  shareType = "st-veg",
  variationId = FAMILY.id!,
}: RenderOptions = {}) {
  const onClose = vi.fn();
  const onSave = vi.fn();
  const profiler = profileRenders();
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");
  const modal = (open: boolean) => (
    <QueryClientProvider client={queryClient}>
      {profiler.wrap(
        <VirtualComponentModal
          visible={open}
          onClose={onClose}
          share_type={shareType}
          share_type_variation={variationId}
          share_type_variation_name="Family box"
          onSave={onSave}
        />,
      )}
    </QueryClientProvider>
  );
  const view = render(modal(visible));
  return {
    onClose,
    onSave,
    profiler,
    invalidate,
    queryClient,
    setVisible: (open: boolean) => view.rerender(modal(open)),
  };
}

const dialog = () => screen.getByRole("dialog");
const checkbox = (label: string) =>
  within(dialog()).getByRole("checkbox", { name: label });

/** The quantity field on a variation's line, if it is selected. */
function quantityOf(label: string): HTMLElement | null {
  const line = checkbox(label).closest(".flex-between");
  if (!line) throw new Error(`No line for ${label}`);
  return line.querySelector<HTMLElement>("input[role='spinbutton']");
}

async function loaded() {
  await screen.findByRole("checkbox", { name: SMALL_LABEL });
}

// ── What is shown ───────────────────────────────────────────────────────────

describe("VirtualComponentModal contents", () => {
  it("lists the share type's other physical variations for the variation it was opened for", async () => {
    renderModal();
    await loaded();

    expect(api.listVariations).toHaveBeenCalledWith({ share_type: "st-veg", physical: true });
    expect(api.listComponents).toHaveBeenCalledWith({ virtual_variation: "var-family" });
    expect(within(dialog()).getByText(/commissioning\.virtual_components_for/)).toHaveTextContent(
      "commissioning.virtual_components_for Family box",
    );
    expect(within(dialog()).getAllByRole("checkbox")).toHaveLength(2);
    expect(checkbox(SMALL_LABEL)).not.toBeChecked();
    expect(checkbox(LARGE_LABEL)).not.toBeChecked();
    expect(within(dialog()).queryByText("commissioning.XL")).not.toBeInTheDocument();
    expect(within(dialog()).queryByRole("spinbutton")).not.toBeInTheDocument();
  });

  it("checks the variations the virtual variation is already packed from, with their quantities", async () => {
    serverComponents = [component("var-large", 3)];
    renderModal();
    await loaded();

    await waitFor(() => expect(checkbox(LARGE_LABEL)).toBeChecked());
    expect(checkbox(SMALL_LABEL)).not.toBeChecked();
    expect(quantityOf(LARGE_LABEL)).toHaveValue("3");
    expect(quantityOf(SMALL_LABEL)).toBeNull();
  });

  it("says so when the share type has no other physical variation", async () => {
    api.listVariations.mockImplementation(async () => [FAMILY]);
    renderModal();

    expect(await screen.findByText("commissioning.no_other_variations")).toBeInTheDocument();
    expect(within(dialog()).queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("asks nothing while it is closed or has no variation", async () => {
    renderModal({ visible: false });
    renderModal({ variationId: null });
    await flushMicrotasks();

    expect(api.listVariations).not.toHaveBeenCalled();
    expect(api.listComponents).not.toHaveBeenCalled();
  });

  it("keeps save disabled while the lists load", async () => {
    let answer: (rows: ShareTypeVariation[]) => void = () => {};
    api.listVariations.mockImplementation(
      () => new Promise<ShareTypeVariation[]>((resolve) => { answer = resolve; }),
    );
    renderModal();

    const save = await screen.findByRole("button", { name: SAVE });
    expect(save).toBeDisabled();

    answer([SMALL, LARGE, FAMILY]);
    await loaded();
    expect(screen.getByRole("button", { name: SAVE })).toBeEnabled();
  });

  it("settles after mounting instead of re-rendering in a loop", async () => {
    serverComponents = [component("var-small", 2)];
    const { profiler } = renderModal();
    await loaded();
    await flushMicrotasks();

    expect(profiler.onRender.mock.calls.length).toBeLessThan(80);
  });
});

// ── Editing ─────────────────────────────────────────────────────────────────

describe("VirtualComponentModal editing", () => {
  it("starts a newly checked variation at one and drops it again when unchecked", async () => {
    const user = userEvent.setup();
    renderModal();
    await loaded();

    await user.click(checkbox(SMALL_LABEL));
    expect(quantityOf(SMALL_LABEL)).toHaveValue("1");

    await user.click(checkbox(SMALL_LABEL));
    expect(quantityOf(SMALL_LABEL)).toBeNull();
  });

  it("takes whole numbers only: a decimal comma or point is not typed", async () => {
    const user = userEvent.setup();
    renderModal();
    await loaded();
    await user.click(checkbox(SMALL_LABEL));
    const quantity = quantityOf(SMALL_LABEL)!;

    await user.clear(quantity);
    await user.type(quantity, "3,");
    expect(quantity).toHaveValue("3");
    await user.type(quantity, ".");
    expect(quantity).toHaveValue("3");
    expect(quantity).toHaveAttribute("inputmode", "numeric");
  });

  it("replaces a saved quantity with the one typed over it", async () => {
    const user = userEvent.setup();
    serverComponents = [component("var-small", 2)];
    renderModal();
    await loaded();
    await waitFor(() => expect(quantityOf(SMALL_LABEL)).toHaveValue("2"));
    const quantity = quantityOf(SMALL_LABEL)!;

    await user.clear(quantity);
    await user.type(quantity, "3");
    expect(quantity).toHaveValue("3");
    await user.click(screen.getByRole("button", { name: SAVE }));

    await waitFor(() =>
      expect(api.saveComponents).toHaveBeenCalledWith({
        virtual_variation: "var-family",
        components: [{ physical_variation: "var-small", quantity: "3" }],
      }),
    );
  });

  it("does not let a background refetch overwrite edits in progress", async () => {
    const user = userEvent.setup();
    serverComponents = [component("var-large", 2)];
    const { queryClient } = renderModal();
    await loaded();
    await waitFor(() => expect(checkbox(LARGE_LABEL)).toBeChecked());

    await user.click(checkbox(SMALL_LABEL));
    await user.click(checkbox(LARGE_LABEL));
    serverComponents = [component("var-large", 4)];
    // A refetch of every query, as a window focus triggers.
    await queryClient.refetchQueries();
    await flushMicrotasks();

    expect(api.listComponents).toHaveBeenCalledTimes(2);

    expect(checkbox(SMALL_LABEL)).toBeChecked();
    expect(checkbox(LARGE_LABEL)).not.toBeChecked();
  });
});

// ── Saving ──────────────────────────────────────────────────────────────────

describe("VirtualComponentModal saving", () => {
  it("sends every selected variation with its quantity as a string, then reports and closes", async () => {
    const user = userEvent.setup();
    serverComponents = [component("var-large", 2)];
    const { onSave, onClose, invalidate } = renderModal();
    await loaded();
    await waitFor(() => expect(checkbox(LARGE_LABEL)).toBeChecked());

    await user.click(checkbox(SMALL_LABEL));
    const quantity = quantityOf(SMALL_LABEL)!;
    await user.clear(quantity);
    await user.type(quantity, "3");
    await user.click(screen.getByRole("button", { name: SAVE }));

    await waitFor(() => expect(api.saveComponents).toHaveBeenCalledTimes(1));
    expect(api.saveComponents).toHaveBeenCalledWith({
      virtual_variation: "var-family",
      components: [
        { physical_variation: "var-large", quantity: "2" },
        { physical_variation: "var-small", quantity: "3" },
      ],
    });
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(onSave).toHaveBeenCalledWith({
      share_type_variation: "var-family",
      components: [
        { physical_variation: "var-large", quantity: 2 },
        { physical_variation: "var-small", quantity: 3 },
      ],
    });
    expect(notify.success).toHaveBeenCalledWith("common.saved_successfully");
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: [
        "/api/commissioning/virtual_variation_components/",
        { virtual_variation: "var-family" },
      ],
    });
  });

  it("sends an empty list when every variation is unchecked", async () => {
    const user = userEvent.setup();
    serverComponents = [component("var-large", 2)];
    renderModal();
    await loaded();
    await waitFor(() => expect(checkbox(LARGE_LABEL)).toBeChecked());

    await user.click(checkbox(LARGE_LABEL));
    await user.click(screen.getByRole("button", { name: SAVE }));

    await waitFor(() =>
      expect(api.saveComponents).toHaveBeenCalledWith({
        virtual_variation: "var-family",
        components: [],
      }),
    );
  });

  it("caps a quantity at five", async () => {
    const user = userEvent.setup();
    renderModal();
    await loaded();
    await user.click(checkbox(SMALL_LABEL));
    const quantity = quantityOf(SMALL_LABEL)!;

    await user.clear(quantity);
    await user.type(quantity, "9");
    await user.tab();
    expect(quantity).toHaveValue("5");
    await user.click(screen.getByRole("button", { name: SAVE }));

    await waitFor(() =>
      expect(api.saveComponents).toHaveBeenCalledWith({
        virtual_variation: "var-family",
        components: [{ physical_variation: "var-small", quantity: "5" }],
      }),
    );
  });

  it("saves a cleared quantity as one", async () => {
    const user = userEvent.setup();
    serverComponents = [component("var-small", 4)];
    renderModal();
    await loaded();
    await waitFor(() => expect(quantityOf(SMALL_LABEL)).toHaveValue("4"));

    await user.clear(quantityOf(SMALL_LABEL)!);
    await user.click(screen.getByRole("button", { name: SAVE }));

    await waitFor(() =>
      expect(api.saveComponents).toHaveBeenCalledWith({
        virtual_variation: "var-family",
        components: [{ physical_variation: "var-small", quantity: "1" }],
      }),
    );
  });

  it("shows the backend's reason and stays open when the save is refused", async () => {
    const user = userEvent.setup();
    api.saveComponents.mockRejectedValue({
      isAxiosError: true,
      response: { status: 400, data: { message: "A component must be physical." } },
    });
    const { onSave, onClose } = renderModal();
    await loaded();
    await user.click(checkbox(SMALL_LABEL));

    await user.click(screen.getByRole("button", { name: SAVE }));

    await waitFor(() =>
      expect(notify.error).toHaveBeenCalledWith("A component must be physical."),
    );
    expect(onSave).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
    expect(notify.success).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: SAVE })).toBeEnabled();
    expect(checkbox(SMALL_LABEL)).toBeChecked();
  });

  it("closes without saving on cancel", async () => {
    const user = userEvent.setup();
    const { onClose, onSave } = renderModal();
    await loaded();
    await user.click(checkbox(SMALL_LABEL));

    await user.click(screen.getByRole("button", { name: CANCEL }));

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onSave).not.toHaveBeenCalled();
    expect(api.saveComponents).not.toHaveBeenCalled();
  });

  it("forgets unsaved selections when closed and reopened", async () => {
    const user = userEvent.setup();
    serverComponents = [component("var-large", 2)];
    const { setVisible } = renderModal();
    await loaded();
    await waitFor(() => expect(checkbox(LARGE_LABEL)).toBeChecked());
    await user.click(checkbox(SMALL_LABEL));
    await user.click(checkbox(LARGE_LABEL));

    setVisible(false);
    await flushMicrotasks();
    setVisible(true);

    await waitFor(() => expect(checkbox(LARGE_LABEL)).toBeChecked());
    expect(checkbox(SMALL_LABEL)).not.toBeChecked();
    expect(quantityOf(LARGE_LABEL)).toHaveValue("2");
  });
});
