/**
 * ShareTypeSelector defaults to preserveSelection=true, so a deliberate
 * share-type pick is reconciled against the freshly-loaded options on a
 * year/week change instead of springing back to the first option (or, worse,
 * a stale invalid value persisting — the AmountShareTypeVariations bug this fixes).
 *
 * antd Select is stubbed: the behavior under test is the reconciliation
 * effect that fires setSelectedShareType, not the rendered widget.
 */
import { render, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("antd", () => ({
  Select: () => null,
}));

const mockUseShareTypes = vi.fn();
vi.mock("@hooks/index", () => ({
  useShareTypes: () => mockUseShareTypes(),
  useIsMobile: () => false,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

import ShareTypeSelector from "../ShareTypeSelector";

const SHARE_TYPES = [
  { value: "veg", label: "Gemüse" },
  { value: "honey", label: "Honig" },
];

describe("ShareTypeSelector — preserveSelection default", () => {
  it("keeps a still-valid pick when year/week changes (no spring-back to first)", async () => {
    mockUseShareTypes.mockReturnValue({ shareTypes: SHARE_TYPES, loading: false });
    const setSelectedShareType = vi.fn();

    render(
      <ShareTypeSelector
        selectedShareType="honey"
        setSelectedShareType={setSelectedShareType}
        year={2026}
        delivery_week={10}
      />,
    );

    await Promise.resolve();
    // "honey" is still offered → the selector must NOT reset it to "veg".
    expect(setSelectedShareType).not.toHaveBeenCalled();
  });

  it("falls back to the first option when the pick is no longer offered", async () => {
    mockUseShareTypes.mockReturnValue({ shareTypes: SHARE_TYPES, loading: false });
    const setSelectedShareType = vi.fn();

    render(
      <ShareTypeSelector
        selectedShareType="gone"
        setSelectedShareType={setSelectedShareType}
        year={2026}
        delivery_week={10}
      />,
    );

    await waitFor(() =>
      expect(setSelectedShareType).toHaveBeenCalledWith("veg"),
    );
  });
});
