/**
 * RichTextEditorModal with the real Quill editor, which converts the stored
 * HTML it is given as soon as the modal opens.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

// The canonical mock, with one `t` for every render as react-i18next keeps it:
// the editor re-validates its text whenever `t` changes.
const i18nMock = vi.hoisted(() => ({
  t: (key: string, fallback?: unknown) =>
    typeof fallback === "string" ? fallback : key,
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: i18nMock.t,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

import RichTextEditorModal from "../RichTextEditorModal";

// Word's list markup: Quill rebuilds each list item in an element of the
// page's own document.
const WORD_LIST_HTML =
  '<html xmlns:w="urn:schemas-microsoft-com:office:word"><body>' +
  '<p style="mso-list:l0 level1">Bring&nbsp;a&nbsp;bag<word-list-probe></word-list-probe></p>' +
  "</body></html>";

// The HTML the editor saves, with a link Quill opens in a new tab.
const EDITOR_HTML =
  "<h2>Pick-up</h2>" +
  "<p>Collect&nbsp;at&nbsp;the&nbsp;<strong>barn</strong>.</p>" +
  "<ul><li>Bring&nbsp;a&nbsp;bag</li></ul>" +
  '<p><a href="https://example.org/map" rel="noopener noreferrer" target="_blank">Map</a></p>';

describe("RichTextEditorModal with Quill", () => {
  it("opens Word list markup without running anything in it", async () => {
    const constructed = vi.fn();
    customElements.define(
      "word-list-probe",
      class extends HTMLElement {
        constructor() {
          super();
          constructed();
        }
      },
    );

    render(
      <RichTextEditorModal
        visible
        value={WORD_LIST_HTML}
        onSave={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(await screen.findByText("Bring a bag")).toBeInTheDocument();
    expect(constructed).not.toHaveBeenCalled();
  });

  it("saves the editor's own HTML unchanged", async () => {
    const onSave = vi.fn();
    const onClose = vi.fn();
    render(
      <RichTextEditorModal
        visible
        value={EDITOR_HTML}
        onSave={onSave}
        onClose={onClose}
      />,
    );
    expect(await screen.findByText("Map")).toHaveAttribute("target", "_blank");

    await userEvent.click(screen.getByRole("button", { name: /common\.save/ }));

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(onSave).toHaveBeenCalledWith(EDITOR_HTML);
  });
});
