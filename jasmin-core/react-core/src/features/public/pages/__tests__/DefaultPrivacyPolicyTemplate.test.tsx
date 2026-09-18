import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

// ``vi.mock`` factories are hoisted above the imports; the spy the assertions
// read therefore has to come from ``vi.hoisted``.
const mocks = vi.hoisted(() => ({
  formatDate: vi.fn(),
}));

// Marker formatter: the rendered date must carry the marker, which proves the
// template went through the tenant's formatter instead of printing the raw
// ISO string.
const markFormatted = (value: unknown) => `<<formatted ${String(value)}>>`;

vi.mock("@hooks/index", () => ({
  useDateFormat: () => ({ formatDate: mocks.formatDate }),
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

import DefaultPrivacyPolicyTemplate from "../DefaultPrivacyPolicyTemplate";

const tenant = {
  name: "Sunfield Farm Cooperative",
  address: "12 Meadow Lane",
  zip_code: "10115",
  city: "Springfield",
  country: "Germany",
  email: "privacy@sunfield.test",
  phone_number: "+49 30 555 0100",
};

beforeEach(() => {
  // ``setup.ts`` restores mocks after every test, so re-arm the implementation.
  mocks.formatDate.mockReset();
  mocks.formatDate.mockImplementation(markFormatted);
});

describe("DefaultPrivacyPolicyTemplate", () => {
  it("prints the tenant's identity in the controller section", () => {
    render(<DefaultPrivacyPolicyTemplate tenant={tenant} />);

    const controllerBlock = screen.getByText(tenant.name).parentElement;
    expect(controllerBlock).not.toBeNull();

    expect(controllerBlock).toHaveTextContent(tenant.address);
    expect(controllerBlock).toHaveTextContent(tenant.country);
    expect(controllerBlock).toHaveTextContent(tenant.email);
    expect(controllerBlock).toHaveTextContent(tenant.phone_number);
    // Postcode and city share one line.
    expect(controllerBlock).toHaveTextContent(
      `${tenant.zip_code} ${tenant.city}`,
    );
  });

  it.each([
    ["null", null],
    ["undefined", undefined],
  ])("renders the whole policy without crashing when the tenant is %s", (
    _label,
    value,
  ) => {
    render(<DefaultPrivacyPolicyTemplate tenant={value} />);

    expect(
      screen.getByRole("heading", { name: "privacy.title", level: 2 }),
    ).toBeInTheDocument();
    // Both ends of the document render — every tenant access is optional.
    expect(screen.getByText("privacy.controller_title")).toBeInTheDocument();
    expect(screen.getByText("privacy.authority_text")).toBeInTheDocument();
  });

  it("renders the last-updated date through the tenant date formatter, never raw", () => {
    render(<DefaultPrivacyPolicyTemplate tenant={tenant} />);

    expect(mocks.formatDate).toHaveBeenCalledTimes(1);
    const rawDate = String(mocks.formatDate.mock.calls[0][0]);
    expect(rawDate).toMatch(/^\d{4}-\d{2}-\d{2}$/);

    expect(
      screen.getByText(`privacy.last_updated: ${markFormatted(rawDate)}`),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(`privacy.last_updated: ${rawDate}`),
    ).not.toBeInTheDocument();
  });

  it("lists every data-subject right the template promises", () => {
    render(<DefaultPrivacyPolicyTemplate tenant={tenant} />);

    const rights = [
      "privacy.right_access",
      "privacy.right_rectification",
      "privacy.right_erasure",
      "privacy.right_restriction",
      "privacy.right_portability",
      "privacy.right_objection",
    ];

    for (const right of rights) {
      expect(screen.getByText(right).tagName).toBe("LI");
    }
  });
});
