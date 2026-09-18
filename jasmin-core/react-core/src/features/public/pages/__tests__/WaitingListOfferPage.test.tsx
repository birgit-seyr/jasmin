/**
 * WaitingListOfferPage — the anonymous magic-link accept/decline page.
 *
 * The ``:token`` route param IS the credential, so every token assertion here
 * checks the ARGUMENT the API call received rather than merely that a call
 * happened: handing accept/decline a token other than the one the page
 * fetched would be a silent cross-offer write, and a "was it called" test
 * cannot see it. The page is therefore mounted on the real
 * ``/waiting-list-offer/:token`` route through a ``MemoryRouter`` instead of a
 * stubbed ``useParams``, so the token genuinely travels URL → hook → request.
 *
 * The branch earning the most coverage is accept's error handling:
 * ``waiting_list_offer.expired`` maps to the dedicated expired screen while
 * every other failure maps to the generic error screen. Decline has no such
 * special case — an asymmetry pinned explicitly below, so a later "tidy-up"
 * that unifies the two handlers has to change a failing test to do it.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { flushMicrotasks, profileRenders } from "@/test/profileRenders";
import type { WaitingListOfferDetail } from "@shared/api/generated/models/waitingListOfferDetail";

// ── Mocks ───────────────────────────────────────────────────────────────────

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

vi.mock("@hooks/index", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const dayjsModule = await import("dayjs");

  // Built once, outside the hook factories, so a re-render never hands the
  // page a fresh object identity — that would defeat the render-loop smoke
  // test at the bottom of this file.
  const tenant = makeUseTenantMock({ displayLogoUrl: null });
  const currency = {
    currencyCode: "EUR",
    currencySymbol: "€",
    formatCurrency: (amount: number) => `${amount} €`,
  };
  // Formats to a shape the raw ISO string cannot accidentally match, so
  // "02.03.2026" in the DOM proves the page routed the date through
  // useDateFormat rather than printing data.valid_from verbatim.
  const dateFormat = {
    dateFormat: "DD.MM.YYYY",
    formatDate: (value: unknown) =>
      value ? dayjsModule.default(value as string).format("DD.MM.YYYY") : null,
  };
  // Deliberately NOT the identity function: a raw "M" reaching the DOM means
  // the page skipped the localizing lookup.
  const sizeLabels: Record<string, string> = { M: "Medium", L: "Large" };
  const sizeOptions = {
    getShareTypeVariationSizeLabel: (value: string) =>
      sizeLabels[value] ?? value,
  };

  return {
    useTenant: () => tenant,
    useCurrency: () => currency,
    useDateFormat: () => dateFormat,
    useShareTypeVariationSizeOptions: () => sizeOptions,
  };
});

// Read lazily inside the arrows, so plain module-scope consts are safe here
// (only a DIRECT property value would need vi.hoisted).
const retrieveMock = vi.fn();
const acceptMock = vi.fn();
const declineMock = vi.fn();

vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  useCommissioningWaitingListOffersRetrieve: (
    token: string,
    options?: unknown,
  ) => retrieveMock(token, options),
  commissioningWaitingListOffersAcceptCreate: (token: string) =>
    acceptMock(token),
  commissioningWaitingListOffersDeclineCreate: (token: string) =>
    declineMock(token),
}));

// ── Import under test (after mocks) ─────────────────────────────────────────

import WaitingListOfferPage from "../WaitingListOfferPage";

// ── Fixtures & helpers ──────────────────────────────────────────────────────

const TOKEN = "wlo-tok-7f3c9";

function makeOffer(
  overrides: Partial<WaitingListOfferDetail> = {},
): WaitingListOfferDetail {
  return {
    member_first_name: "Mara",
    variation_name: "Vegetable Box",
    variation_size: "M",
    delivery_station_name: "Market Square",
    delivery_station_address: "Market Square 4, Springfield",
    valid_from: "2026-03-02",
    valid_until: "2026-09-27",
    quantity: 2,
    price_per_delivery: "24.50",
    status: "sent",
    expires_at: "2026-02-20",
    expired: false,
    ...overrides,
  };
}

/** Shape of the mocked generated query hook's return value. */
function queryResult(
  over: {
    data?: WaitingListOfferDetail;
    isLoading?: boolean;
    isError?: boolean;
  } = {},
) {
  return { data: undefined, isLoading: false, isError: false, ...over };
}

/** The offer loaded successfully — the default for most cases below. */
function loadedOffer(overrides: Partial<WaitingListOfferDetail> = {}) {
  retrieveMock.mockReturnValue(queryResult({ data: makeOffer(overrides) }));
}

function renderPage(token: string = TOKEN) {
  return render(
    <MemoryRouter initialEntries={[`/waiting-list-offer/${token}`]}>
      <Routes>
        <Route
          path="/waiting-list-offer/:token"
          element={<WaitingListOfferPage />}
        />
      </Routes>
    </MemoryRouter>,
  );
}

const acceptButton = () =>
  screen.queryByRole("button", { name: "abos.offer_page.accept" });
const declineButton = () =>
  screen.queryByRole("button", { name: "abos.offer_page.decline" });

/** Value cell of a bordered <Descriptions> row, found via its label. */
function descriptionValue(label: string): string {
  const row = screen.getByText(label).closest("tr");
  const content = row?.querySelector(".ant-descriptions-item-content");
  return content?.textContent ?? "";
}

/**
 * getErrorCode() only reads a code off something axios-shaped — a plain Error
 * yields undefined and falls through to the generic branch.
 */
function axiosErrorWithCode(code: string) {
  return { isAxiosError: true, response: { data: { code } } };
}

beforeEach(() => {
  retrieveMock.mockReset();
  acceptMock.mockReset().mockResolvedValue(undefined);
  declineMock.mockReset().mockResolvedValue(undefined);
});

// ── Pre-offer states ────────────────────────────────────────────────────────

describe("loading and unavailable states", () => {
  it("shows a spinner and offers no action while the offer is loading", () => {
    retrieveMock.mockReturnValue(queryResult({ isLoading: true }));

    const { container } = renderPage();

    expect(container.querySelector(".ant-spin")).toBeInTheDocument();
    expect(screen.queryAllByRole("button")).toHaveLength(0);
    expect(screen.queryByText("abos.offer_page.intro")).not.toBeInTheDocument();
  });

  it("shows the invalid-link result and no actions when the fetch errors", () => {
    // The payload is present on purpose: a failed refetch keeps the last good
    // data, so the error flag — not the empty-payload case below — is the only
    // thing that can produce this screen. With `data` left undefined the
    // assertion would hold even if the page ignored `isError` entirely.
    retrieveMock.mockReturnValue(
      queryResult({ isError: true, data: makeOffer() }),
    );

    renderPage();

    expect(screen.getByText("abos.offer_page.invalid_title")).toBeInTheDocument();
    expect(screen.getByText("abos.offer_page.invalid_text")).toBeInTheDocument();
    expect(screen.queryAllByRole("button")).toHaveLength(0);
    // The stale offer body must not leak through alongside the error screen.
    expect(screen.queryByText("abos.offer_page.intro")).not.toBeInTheDocument();
  });

  it("treats a successful-but-empty response as an invalid link", () => {
    // Not an error state, just no payload — the page must not render an
    // offer skeleton with blank fields.
    retrieveMock.mockReturnValue(queryResult({ data: undefined }));

    renderPage();

    expect(screen.getByText("abos.offer_page.invalid_title")).toBeInTheDocument();
    expect(screen.queryAllByRole("button")).toHaveLength(0);
  });
});

// ── The loaded offer ────────────────────────────────────────────────────────

describe("a loaded offer", () => {
  it("renders the offer details and both actions", () => {
    loadedOffer();

    renderPage();

    expect(screen.getByText("abos.offer_page.intro")).toBeInTheDocument();
    expect(screen.getByText("Market Square")).toBeInTheDocument();
    expect(screen.getByText("Market Square 4, Springfield")).toBeInTheDocument();
    // Dates go through useDateFormat — the raw ISO value must not surface.
    expect(descriptionValue("abos.offer_page.start")).toBe("02.03.2026");
    expect(descriptionValue("abos.offer_page.end")).toBe("27.09.2026");
    expect(descriptionValue("abos.offer_page.reply_by")).toBe("20.02.2026");
    expect(screen.queryByText("2026-03-02")).not.toBeInTheDocument();
    // Price is prefixed with the tenant currency symbol.
    expect(descriptionValue("abos.offer_page.price")).toBe("€ 24.50");
    expect(acceptButton()).toBeInTheDocument();
    expect(declineButton()).toBeInTheDocument();
  });

  it("fetches the offer named by the URL token", () => {
    loadedOffer();

    renderPage("tok-from-the-url-42");

    expect(retrieveMock.mock.calls[0][0]).toBe("tok-from-the-url-42");
  });

  it("omits a detail row whose value the payload does not carry", () => {
    loadedOffer({ delivery_station_name: "", price_per_delivery: null });

    renderPage();

    expect(
      screen.queryByText("abos.offer_page.station"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("abos.offer_page.price")).not.toBeInTheDocument();
    // A row that IS present still renders, so this is not a blank page.
    expect(screen.getByText("abos.offer_page.start")).toBeInTheDocument();
  });
});

// ── Share-label composition ─────────────────────────────────────────────────

describe("share label composition", () => {
  it("joins quantity, name and the LOCALIZED size", () => {
    loadedOffer({ quantity: 2, variation_name: "Vegetable Box", variation_size: "M" });

    renderPage();

    expect(descriptionValue("abos.offer_page.share")).toBe(
      "2 × Vegetable Box Medium",
    );
  });

  it("drops the quantity prefix when there is no quantity", () => {
    loadedOffer({ quantity: 0, variation_name: "Vegetable Box", variation_size: "L" });

    renderPage();

    expect(descriptionValue("abos.offer_page.share")).toBe("Vegetable Box Large");
  });

  it("omits the share row entirely when neither name nor size is known", () => {
    loadedOffer({ variation_name: "", variation_size: "" });

    renderPage();

    expect(screen.queryByText("abos.offer_page.share")).not.toBeInTheDocument();
  });

  it("keeps the share row on the size alone when the name is missing", () => {
    // The row is driven by name-OR-size, not by name: a nameless offer that
    // still knows its size shows the size rather than vanishing.
    loadedOffer({ variation_name: "", variation_size: "M", quantity: 3 });

    renderPage();

    expect(descriptionValue("abos.offer_page.share")).toBe("3 × Medium");
  });
});

// ── Accept ──────────────────────────────────────────────────────────────────

describe("accepting", () => {
  it("posts the URL token and shows the accepted result", async () => {
    loadedOffer();

    renderPage("tok-from-the-url-42");
    await userEvent.click(acceptButton()!);

    expect(acceptMock).toHaveBeenCalledWith("tok-from-the-url-42");
    expect(
      await screen.findByText("abos.offer_page.accepted_title"),
    ).toBeInTheDocument();
    expect(declineMock).not.toHaveBeenCalled();
    expect(acceptButton()).not.toBeInTheDocument();
  });

  it("shows the EXPIRED result when the offer expired mid-flight", async () => {
    loadedOffer();
    acceptMock.mockRejectedValue(
      axiosErrorWithCode("waiting_list_offer.expired"),
    );

    renderPage();
    await userEvent.click(acceptButton()!);

    expect(
      await screen.findByText("abos.offer_page.expired_title"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("abos.offer_page.error_title"),
    ).not.toBeInTheDocument();
  });

  it("shows the generic error result for any other error code", async () => {
    loadedOffer();
    acceptMock.mockRejectedValue(
      axiosErrorWithCode("waiting_list_offer.already_answered"),
    );

    renderPage();
    await userEvent.click(acceptButton()!);

    expect(
      await screen.findByText("abos.offer_page.error_title"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("abos.offer_page.expired_title"),
    ).not.toBeInTheDocument();
  });

  it("shows the generic error result for a non-axios failure", async () => {
    // A network-layer throw carries no readable code, so it must not be
    // mistaken for the expired case.
    loadedOffer();
    acceptMock.mockRejectedValue(new Error("Network Error"));

    renderPage();
    await userEvent.click(acceptButton()!);

    expect(
      await screen.findByText("abos.offer_page.error_title"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("abos.offer_page.expired_title"),
    ).not.toBeInTheDocument();
  });
});

// ── Decline ─────────────────────────────────────────────────────────────────

describe("declining", () => {
  it("posts the URL token and shows the declined result", async () => {
    loadedOffer();

    renderPage("tok-from-the-url-42");
    await userEvent.click(declineButton()!);

    expect(declineMock).toHaveBeenCalledWith("tok-from-the-url-42");
    expect(
      await screen.findByText("abos.offer_page.declined_title"),
    ).toBeInTheDocument();
    expect(acceptMock).not.toHaveBeenCalled();
    expect(declineButton()).not.toBeInTheDocument();
  });

  it("falls to the generic error result even when the code is expired", async () => {
    // Asymmetry with accept, and intentional: decline has no expired
    // special-case, so the expired screen must NOT appear here.
    loadedOffer();
    declineMock.mockRejectedValue(
      axiosErrorWithCode("waiting_list_offer.expired"),
    );

    renderPage();
    await userEvent.click(declineButton()!);

    expect(
      await screen.findByText("abos.offer_page.error_title"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("abos.offer_page.expired_title"),
    ).not.toBeInTheDocument();
  });
});

// ── Already-expired offer ───────────────────────────────────────────────────

describe("an already-expired offer", () => {
  it("shows the expired result and allows no interaction at all", () => {
    loadedOffer({ expired: true });

    renderPage();

    expect(screen.getByText("abos.offer_page.expired_title")).toBeInTheDocument();
    expect(screen.getByText("abos.offer_page.expired_text")).toBeInTheDocument();
    expect(screen.queryAllByRole("button")).toHaveLength(0);
    expect(acceptMock).not.toHaveBeenCalled();
    expect(declineMock).not.toHaveBeenCalled();
  });
});

// ── Render-loop smoke ───────────────────────────────────────────────────────

describe("render loop", () => {
  it("settles without a render loop", async () => {
    loadedOffer();
    const profiler = profileRenders();

    render(
      profiler.wrap(
        <MemoryRouter initialEntries={[`/waiting-list-offer/${TOKEN}`]}>
          <Routes>
            <Route
              path="/waiting-list-offer/:token"
              element={<WaitingListOfferPage />}
            />
          </Routes>
        </MemoryRouter>,
      ),
    );

    await screen.findByText("abos.offer_page.intro");
    await flushMicrotasks();

    // Loose bound: a real setState-in-render loop commits thousands of times.
    expect(profiler.onRender.mock.calls.length).toBeLessThan(50);
  });
});
