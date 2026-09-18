import { describe, expect, it, vi, beforeEach } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Hoisted: the navigate spy is asserted on directly, and the tenant row is
// swapped per test by ``renderPage`` before the component reads it.
const { navigateMock, tenantRow } = vi.hoisted(() => ({
  navigateMock: vi.fn(),
  tenantRow: { current: {} as Record<string, unknown> },
}));

vi.mock("react-router-dom", async () => {
  const actual =
    await vi.importActual<typeof import("react-router-dom")>(
      "react-router-dom",
    );
  return { ...actual, useNavigate: () => navigateMock };
});

// The page renders straight from the tenant row, so the whole suite is a
// matter of handing it different rows. ``tenantRow.current`` is read lazily
// at render time, which is what lets one mock serve every case.
vi.mock("@hooks/index", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  return {
    useTenant: () => makeUseTenantMock({ tenant: tenantRow.current }),
  };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

import PublicLegalNoticePage from "../PublicLegalNoticePage";

/**
 * A realistic imprint with every OPTIONAL field explicitly empty, so an
 * "absent" assertion fails for the right reason and each "present" case
 * flips exactly one field.
 */
const BASE_TENANT = {
  name: "Gärtnerei Sonnenhof e.V.",
  legal_form: "eingetragener Verein",
  address: "Feldweg 12",
  zip_code: "79100",
  city: "Freiburg",
  country: "Deutschland",
  phone_number: "+49 761 1234567",
  email: "info@sonnenhof.example",
  website: "",
  register_type: "",
  register_number: "",
  register_court: "",
  legal_representatives: "",
  supervisory_board: "",
  content_responsible: "",
  auditing_association: "",
  professional_association: "",
  organic_control_number: "",
  uid: "",
  legal_notice_extra_html: "",
  participates_in_dispute_resolution: false,
};

function renderPage(overrides: Record<string, unknown> = {}) {
  tenantRow.current = { ...BASE_TENANT, ...overrides };
  return render(<PublicLegalNoticePage />);
}

beforeEach(() => {
  navigateMock.mockClear();
});

describe("PublicLegalNoticePage", () => {
  it("renders the provider block from the tenant row", () => {
    const { container } = renderPage();

    expect(screen.getByText("impressum.provider_title")).toBeInTheDocument();
    expect(container.textContent).toContain("Gärtnerei Sonnenhof e.V.");
    expect(container.textContent).toContain("eingetragener Verein");
    expect(container.textContent).toContain("Feldweg 12");
    expect(container.textContent).toContain("79100");
    expect(container.textContent).toContain("Freiburg");
  });

  describe("website link safety", () => {
    it("renders a javascript: website as inert text with no anchor at all", () => {
      const { container } = renderPage({ website: "javascript:alert(1)" });

      // The value is still shown to the reader — it is just not clickable.
      expect(container.textContent).toContain("javascript:alert(1)");
      expect(container.querySelector("a")).toBeNull();
      expect(screen.queryByRole("link")).toBeNull();
    });

    it("renders a data: website as inert text with no anchor at all", () => {
      const { container } = renderPage({
        website: "data:text/html,<script>alert(1)</script>",
      });

      expect(container.querySelector("a")).toBeNull();
      expect(screen.queryByRole("link")).toBeNull();
    });

    it("renders an https website as an anchor with target=_blank and rel noopener noreferrer", () => {
      renderPage({ website: "https://sonnenhof.example" });

      const link = screen.getByRole("link", {
        name: "https://sonnenhof.example",
      });
      expect(link).toHaveAttribute("href", "https://sonnenhof.example");
      expect(link).toHaveAttribute("target", "_blank");
      expect(link.getAttribute("rel")).toContain("noopener");
      expect(link.getAttribute("rel")).toContain("noreferrer");
    });

    it("omits the website line entirely when the field is empty", () => {
      const { container } = renderPage();

      expect(container.textContent).not.toContain("impressum.website_label");
    });
  });

  describe("legal_notice_extra_html sanitization", () => {
    it("strips a <script> tag while still rendering the surrounding markup", () => {
      const { container } = renderPage({
        legal_notice_extra_html:
          "<p>Additional imprint paragraph</p>" +
          "<script>window.__impressumPwned = true;</script>",
      });

      // Proves the block rendered — so the test cannot pass by rendering
      // nothing at all.
      expect(
        screen.getByText("Additional imprint paragraph"),
      ).toBeInTheDocument();
      expect(container.querySelector("script")).toBeNull();
      expect(container.innerHTML).not.toContain("__impressumPwned");
    });

    it("strips an inline event handler while keeping the element text", () => {
      const { container } = renderPage({
        legal_notice_extra_html:
          '<p onmouseover="window.__impressumPwned = true">Hover target</p>',
      });

      const paragraph = screen.getByText("Hover target");
      expect(paragraph).toBeInTheDocument();
      expect(paragraph.getAttribute("onmouseover")).toBeNull();
      expect(container.innerHTML).not.toContain("__impressumPwned");
    });

    it("renders no extra-html block when the field is empty", () => {
      // An empty field renders no text, so text alone cannot witness the
      // block's absence. The sanitized-HTML host is the only attribute-less
      // <div> in the tree — everything AntD renders carries a class, and the
      // page wrapper a style — which makes it the one usable handle.
      const extraHtmlHosts = (root: HTMLElement) =>
        root.querySelectorAll("div:not([class]):not([style])");

      // Calibration: the selector demonstrably matches the block when it does
      // render, so the absence assertion below cannot pass by matching nothing.
      const present = renderPage({
        legal_notice_extra_html: "<p>Additional imprint paragraph</p>",
      });
      expect(extraHtmlHosts(present.container)).toHaveLength(1);
      cleanup();

      const absent = renderPage();
      expect(extraHtmlHosts(absent.container)).toHaveLength(0);
      expect(screen.queryByText("Additional imprint paragraph")).toBeNull();
    });
  });

  describe("register block", () => {
    it.each([
      ["register_type", "Vereinsregister"],
      ["register_number", "VR 1234"],
      ["register_court", "Amtsgericht Freiburg"],
    ])("appears when only %s is set", (field, value) => {
      const { container } = renderPage({ [field]: value });

      expect(screen.getByText("impressum.register_title")).toBeInTheDocument();
      expect(container.textContent).toContain(value);
    });

    it("joins type and number on one line when both are set", () => {
      const { container } = renderPage({
        register_type: "Vereinsregister",
        register_number: "VR 1234",
      });

      expect(container.textContent).toContain("Vereinsregister: VR 1234");
    });

    it("is absent when type, number and court are all empty", () => {
      renderPage();

      expect(screen.queryByText("impressum.register_title")).toBeNull();
      expect(
        screen.queryByText("impressum.register_court_label"),
      ).toBeNull();
    });
  });

  describe("optional blocks", () => {
    const OPTIONAL_BLOCKS: Array<[string, string, string]> = [
      [
        "legal_representatives",
        "impressum.represented_by_title",
        "Vorstand: Anna Beispiel",
      ],
      [
        "supervisory_board",
        "impressum.supervisory_board_title",
        "Aufsichtsrat: Maria Beispiel",
      ],
      ["uid", "impressum.vat_title", "DE123456789"],
      [
        "organic_control_number",
        "impressum.organic_control_title",
        "DE-OEKO-001",
      ],
      [
        "auditing_association",
        "impressum.auditing_association_title",
        "Genossenschaftsverband Sued",
      ],
      [
        "professional_association",
        "impressum.professional_association_title",
        "SVLFG, Kassel",
      ],
      [
        "content_responsible",
        "impressum.content_responsible_title",
        "Jana Beispiel",
      ],
    ];

    it.each(OPTIONAL_BLOCKS)(
      "omits the %s block when the field is empty",
      (_field, titleKey) => {
        renderPage();

        expect(screen.queryByText(titleKey)).toBeNull();
      },
    );

    it.each(OPTIONAL_BLOCKS)(
      "renders the %s block when the field is set",
      (field, titleKey, value) => {
        const { container } = renderPage({ [field]: value });

        expect(screen.getByText(titleKey)).toBeInTheDocument();
        expect(container.textContent).toContain(value);
      },
    );
  });

  describe("dispute resolution", () => {
    it("states willingness when participates_in_dispute_resolution is true", () => {
      renderPage({ participates_in_dispute_resolution: true });

      expect(
        screen.getByText("impressum.dispute_resolution_yes"),
      ).toBeInTheDocument();
      expect(screen.queryByText("impressum.dispute_resolution_no")).toBeNull();
    });

    it("states non-participation when it is false", () => {
      renderPage({ participates_in_dispute_resolution: false });

      expect(
        screen.getByText("impressum.dispute_resolution_no"),
      ).toBeInTheDocument();
      expect(screen.queryByText("impressum.dispute_resolution_yes")).toBeNull();
    });
  });

  it("goes back in history when the back button is clicked", async () => {
    renderPage();

    await userEvent.click(
      screen.getByRole("button", { name: /common\.back/ }),
    );

    expect(navigateMock).toHaveBeenCalledWith(-1);
  });
});
