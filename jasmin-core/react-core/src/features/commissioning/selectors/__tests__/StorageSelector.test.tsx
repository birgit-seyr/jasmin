/**
 * StorageSelector: lists the active storages, always keeps one picked and
 * fills the phone's width. Rendered inside a small page that holds the pick in
 * state, as the documentation pages do. The generated commissioning client is
 * the mocking boundary: its storages hook is a real TanStack query around a spy.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Storage } from "@shared/api/generated/models";
import { flushMicrotasks } from "@/test/profileRenders";

const i18nMock = vi.hoisted(() => ({
  t: (key: string, fallback?: unknown) => (typeof fallback === "string" ? fallback : key),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: i18nMock.t,
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

const device = vi.hoisted(() => ({ mobile: false }));
vi.mock("@hooks/configuration/useIsMobile", () => ({ useIsMobile: () => device.mobile }));

const api = vi.hoisted(() => ({ storages: vi.fn() }));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  return {
    useCommissioningStoragesList: function useStoragesQuery(params?: unknown) {
      return useQuery({
        queryKey: ["/api/commissioning/storages/", params],
        queryFn: async () => api.storages(params),
      });
    },
  };
});

import StorageSelector from "../StorageSelector";

// ── Fixtures ────────────────────────────────────────────────────────────────

const storage = (id: string | undefined, name: string): Storage => ({ id, name, is_active: true });

const COLD_ROOM = storage("st-cold", "Kühlraum");
const CELLAR = storage("st-cellar", "Keller");
// A row without an id can't be picked.
const UNSAVED = storage(undefined, "Neu");

// ── Helpers ─────────────────────────────────────────────────────────────────

let picked: string | null = null;
const onStorageChange = vi.fn();

type PageProps = { initialStorage?: string | null; includeNone?: boolean; preserveSelection?: boolean };

function Page({ initialStorage = null, includeNone, preserveSelection }: PageProps) {
  const [selected, setSelected] = useState<string | null>(initialStorage);
  picked = selected;
  return (
    <StorageSelector
      selectedStorage={selected}
      setSelectedStorage={setSelected}
      onStorageChange={onStorageChange}
      include_null_option={includeNone}
      preserveSelection={preserveSelection}
    />
  );
}

function renderPage(props: PageProps = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  const view = render(
    <QueryClientProvider client={queryClient}>
      <Page {...props} />
    </QueryClientProvider>,
  );
  return {
    /** The storages list is asked for again and answers with what's there now. */
    reload: () => act(() => queryClient.invalidateQueries()),
    view,
  };
}

const PLACEHOLDER = "placeholder.storage_selector";

const storageSelect = () => screen.getByRole("combobox", { name: PLACEHOLDER });
const selectRoot = () => storageSelect().closest(".ant-select") as HTMLElement;
const shownStorage = () => selectRoot().querySelector(".ant-select-selection-item")?.textContent ?? "";
const placeholderShown = () =>
  selectRoot().querySelector(".ant-select-selection-placeholder")?.textContent ?? "";

function openDropdown(): HTMLElement {
  const open = document.querySelectorAll<HTMLElement>(".ant-select-dropdown:not(.ant-select-dropdown-hidden)");
  if (open.length === 0) throw new Error("No select dropdown is open");
  return open[open.length - 1];
}

const listedStorages = () =>
  Array.from(openDropdown().querySelectorAll(".ant-select-item-option-content")).map((o) => o.textContent);

async function chooseStorage(label: string) {
  await userEvent.click(storageSelect());
  const option = Array.from(openDropdown().querySelectorAll(".ant-select-item-option-content")).find(
    (content) => content.textContent === label,
  );
  if (!option) throw new Error(`No storage ${label}`);
  await userEvent.click(option);
}

const settle = () => act(() => flushMicrotasks());

beforeEach(() => {
  picked = null;
  device.mobile = false;
  onStorageChange.mockReset();
  api.storages.mockReset().mockResolvedValue([COLD_ROOM, CELLAR, UNSAVED]);
});

// ── Options ─────────────────────────────────────────────────────────────────

describe("StorageSelector options", () => {
  it("lists the active storages by name, leaving out rows without an id", async () => {
    renderPage();

    await waitFor(() => expect(api.storages).toHaveBeenCalledWith({ is_active: true }));
    await userEvent.click(storageSelect());
    await waitFor(() => expect(listedStorages()).toEqual(["Kühlraum", "Keller"]));
  });

  it("puts a '-' entry first when asked to and picks it", async () => {
    renderPage({ includeNone: true });

    await waitFor(() => expect(picked).toBe("none"));
    expect(shownStorage()).toBe("-");
    await userEvent.click(storageSelect());
    expect(listedStorages()).toEqual(["-", "Kühlraum", "Keller"]);
  });

  it("is named by its placeholder", () => {
    renderPage();

    expect(storageSelect()).toHaveAccessibleName(PLACEHOLDER);
  });

  it("fills the width on a phone and keeps its fixed width on a desktop", () => {
    const desktop = renderPage();
    expect(selectRoot()).toHaveStyle({ width: "15em" });
    desktop.view.unmount();

    device.mobile = true;
    renderPage();
    expect(selectRoot()).toHaveStyle({ width: "100%" });
  });
});

// ── The pick ────────────────────────────────────────────────────────────────

describe("StorageSelector picks", () => {
  it("picks the first storage without telling the change callback", async () => {
    renderPage();

    await waitFor(() => expect(picked).toBe(COLD_ROOM.id));
    expect(shownStorage()).toBe("Kühlraum");
    await settle();
    expect(onStorageChange).not.toHaveBeenCalled();
  });

  it("keeps the page's storage when it is listed", async () => {
    renderPage({ initialStorage: CELLAR.id });
    await waitFor(() => expect(shownStorage()).toBe("Keller"));
    await settle();

    expect(picked).toBe(CELLAR.id);
  });

  it("falls back to the first storage when the page's storage isn't listed", async () => {
    renderPage({ initialStorage: "st-deactivated" });

    await waitFor(() => expect(picked).toBe(COLD_ROOM.id));
  });

  it("without preserving, keeps any storage the page already has", async () => {
    renderPage({ initialStorage: "st-deactivated", preserveSelection: false });
    await waitFor(() => expect(api.storages).toHaveBeenCalled());
    await settle();

    expect(picked).toBe("st-deactivated");
  });

  it("sends the chosen storage to the page and to the change callback", async () => {
    renderPage();
    await waitFor(() => expect(picked).toBe(COLD_ROOM.id));

    await chooseStorage("Keller");

    expect(picked).toBe(CELLAR.id);
    expect(onStorageChange).toHaveBeenCalledTimes(1);
    expect(onStorageChange).toHaveBeenCalledWith(CELLAR.id);
  });

  it("moves to the first storage left when the picked one is deactivated", async () => {
    const page = renderPage();
    await waitFor(() => expect(picked).toBe(COLD_ROOM.id));
    await chooseStorage("Keller");

    api.storages.mockResolvedValue([COLD_ROOM]);
    await page.reload();

    await waitFor(() => expect(picked).toBe(COLD_ROOM.id));
  });

  it("picks nothing while no storage exists or the list fails to load", async () => {
    api.storages.mockResolvedValue([]);
    const empty = renderPage();
    await waitFor(() => expect(api.storages).toHaveBeenCalled());
    await settle();
    expect(picked).toBeNull();
    expect(placeholderShown()).toBe(PLACEHOLDER);
    empty.view.unmount();

    api.storages.mockRejectedValue(Object.assign(new Error("Network Error"), { isAxiosError: true }));
    renderPage();
    await waitFor(() => expect(api.storages).toHaveBeenCalledTimes(2));
    await settle();
    expect(picked).toBeNull();
    expect(placeholderShown()).toBe(PLACEHOLDER);
  });
});
