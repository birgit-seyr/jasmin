/**
 * ShareArticleSelector: lists the share articles and, when asked to keep a
 * pick, keeps it one of them. Rendered inside a small page that holds the pick
 * in state, as DocumentationOverview and LoggingStorage do. The generated
 * commissioning client is the mocking boundary: its share-articles hook is a
 * real TanStack query around a spy.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ShareArticle } from "@shared/api/generated/models";
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

const api = vi.hoisted(() => ({ shareArticles: vi.fn() }));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  return {
    useCommissioningShareArticlesList: function useShareArticlesQuery(params?: unknown) {
      return useQuery({
        queryKey: ["/api/commissioning/share_articles/", params],
        queryFn: async () => api.shareArticles(params),
      });
    },
  };
});

import ShareArticleSelector from "../ShareArticleSelector";

// ── Fixtures ────────────────────────────────────────────────────────────────

const shareArticle = (id: string, name: string): ShareArticle => ({ id, name }) as ShareArticle;

const CARROTS = shareArticle("sa-carrots", "Carrots");
const LEEKS = shareArticle("sa-leeks", "Leeks");

// ── Helpers ─────────────────────────────────────────────────────────────────

let picked: string | null = null;
const onShareArticleChange = vi.fn();

type PageProps = { initialArticle?: string | null; includeAll?: boolean; preserveSelection?: boolean };

function Page({ initialArticle = null, includeAll, preserveSelection }: PageProps) {
  const [selected, setSelected] = useState<string | null>(initialArticle);
  picked = selected;
  return (
    <ShareArticleSelector
      selectedShareArticle={selected}
      setSelectedShareArticle={setSelected}
      onShareArticleChange={onShareArticleChange}
      include_null_option={includeAll}
      preserveSelection={preserveSelection}
    />
  );
}

function renderPage(props: PageProps = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <Page {...props} />
    </QueryClientProvider>,
  );
  return {
    /** The share articles are asked for again and answer with what's there now. */
    reload: () => act(() => queryClient.invalidateQueries()),
  };
}

const PLACEHOLDER = "placeholder.share_article_selector";
const ALL = "commissioning.all_share_articles";

const articleSelect = () => screen.getByRole("combobox", { name: PLACEHOLDER });
const selectRoot = () => articleSelect().closest(".ant-select") as HTMLElement;
const shownArticle = () => selectRoot().querySelector(".ant-select-selection-item")?.textContent ?? "";

async function chooseArticle(label: string) {
  await userEvent.click(articleSelect());
  const open = document.querySelectorAll<HTMLElement>(".ant-select-dropdown:not(.ant-select-dropdown-hidden)");
  const option = Array.from(
    open[open.length - 1].querySelectorAll(".ant-select-item-option-content"),
  ).find((content) => content.textContent === label);
  if (!option) throw new Error(`No share article ${label}`);
  await userEvent.click(option);
}

const settle = () => act(() => flushMicrotasks());

beforeEach(() => {
  picked = null;
  onShareArticleChange.mockReset();
  api.shareArticles.mockReset().mockResolvedValue([CARROTS, LEEKS]);
});

// ── Look ────────────────────────────────────────────────────────────────────

describe("ShareArticleSelector look", () => {
  it("takes its width from the stylesheet", () => {
    renderPage();

    expect(selectRoot()).toHaveClass("bold-select", "week-selector-select", "share-article-selector");
    expect(selectRoot()).not.toHaveAttribute("style");
  });
});

// ── The pick ────────────────────────────────────────────────────────────────

describe("ShareArticleSelector picks", () => {
  it("picks nothing by itself unless asked to keep a pick", async () => {
    renderPage();
    await waitFor(() => expect(api.shareArticles).toHaveBeenCalled());
    await settle();

    expect(picked).toBeNull();
  });

  it("picks the first share article on mount when keeping a pick", async () => {
    renderPage({ preserveSelection: true });

    await waitFor(() => expect(picked).toBe(CARROTS.id));
    expect(shownArticle()).toBe("Carrots");
    await settle();
    expect(onShareArticleChange).not.toHaveBeenCalled();
  });

  it("keeps a listed pick and falls back to the first article when it goes", async () => {
    const page = renderPage({ preserveSelection: true });
    await waitFor(() => expect(picked).toBe(CARROTS.id));
    await chooseArticle("Leeks");

    await page.reload();
    await settle();
    expect(picked).toBe(LEEKS.id);

    api.shareArticles.mockResolvedValue([CARROTS]);
    await page.reload();
    await waitFor(() => expect(picked).toBe(CARROTS.id));
  });

  it("drops the pick once every share article is gone", async () => {
    const page = renderPage({ preserveSelection: true });
    await waitFor(() => expect(picked).toBe(CARROTS.id));

    api.shareArticles.mockResolvedValue([]);
    await page.reload();

    await waitFor(() => expect(picked).toBeNull());
  });

  it("keeps 'all share articles' when it is offered", async () => {
    renderPage({ preserveSelection: true, includeAll: true });
    await waitFor(() => expect(api.shareArticles).toHaveBeenCalled());
    await settle();

    expect(picked).toBeNull();
    await userEvent.click(articleSelect());
    expect(screen.getAllByText(ALL).length).toBeGreaterThan(0);
  });

  it("without keeping a pick, leaves a share article that isn't listed", async () => {
    renderPage({ initialArticle: "sa-gone" });
    await waitFor(() => expect(api.shareArticles).toHaveBeenCalled());
    await settle();

    expect(picked).toBe("sa-gone");
  });
});
