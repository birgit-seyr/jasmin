/**
 * RichTextEditorModal: the editor for descriptions, delivery-day
 * instructions, the privacy policy and rich-text settings. It closes once the
 * caller's save is done and stays open with the text when the save fails.
 * Quill is replaced by a plain textarea; the rest is real.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

// The canonical mock, with one `t` for every render as react-i18next keeps it:
// the editor re-validates its text whenever `t` changes, so a new `t` per
// render would re-render it forever.
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

vi.mock("react-quill-new", () => ({
  default: ({
    value,
    onChange,
  }: {
    value: string;
    onChange: (content: string) => void;
  }) => (
    <textarea
      aria-label="Text"
      value={value}
      onChange={(event) => onChange(event.target.value)}
    />
  ),
}));

import RichTextEditorModal from "../RichTextEditorModal";

function renderEditor(
  onSave: (content: string) => void | Promise<void>,
  props: {
    value?: string;
    maxLines?: number;
    maxCharacters?: number;
    maxCharsPerLine?: number;
  } = {},
) {
  const onClose = vi.fn();
  render(
    <RichTextEditorModal
      visible
      value="Collect at the barn."
      onSave={onSave}
      onClose={onClose}
      {...props}
    />,
  );
  return { onClose };
}

const saveButton = () => screen.getByRole("button", { name: /common\.save/ });

async function replaceText(text: string) {
  const editor = screen.getByRole("textbox", { name: "Text" });
  await userEvent.clear(editor);
  await userEvent.type(editor, text);
}

// Quill's semantic HTML, which the editor saves: every space is an &nbsp;.
const FOOTER_COLUMN_HTML =
  "<p>Farm&nbsp;Example</p><p>Main&nbsp;Street&nbsp;1</p><p>12345&nbsp;Town</p>";
const INSTRUCTIONS_HTML =
  "<h2>Pick-up</h2>" +
  "<p>Collect&nbsp;at&nbsp;the&nbsp;<strong>barn</strong>.</p>" +
  "<p><br></p>" +
  "<ul><li>Bring&nbsp;a&nbsp;bag</li><li>Ring&nbsp;the&nbsp;<em>bell</em></li></ul>" +
  '<p><a href="https://example.org/map" rel="noopener noreferrer" target="_blank">Map</a>' +
  '&nbsp;and&nbsp;<span style="color: rgb(230, 0, 0);">hours</span></p>';
// The HTML of Quill's editing surface: plain spaces, and a list item carries
// its type and Quill's marker span.
const EDITING_SURFACE_HTML =
  "<p>Collect at the barn.</p><p><br></p>" +
  '<ol><li data-list="bullet"><span class="ql-ui" contenteditable="false"></span>Bring a bag</li>' +
  '<li data-list="ordered"><span class="ql-ui" contenteditable="false"></span>Ring the bell</li></ol>' +
  "<p>Thanks!</p>";

// Stored HTML comes in through the API as free text, so anything may be in it.
const HOSTILE_HTML =
  '<p>Hi&nbsp;there<img src="x" onerror="window.alert(1)"><stored-html-probe></stored-html-probe></p>';

describe("RichTextEditorModal", () => {
  it("opens with the stored text", () => {
    renderEditor(vi.fn());

    expect(screen.getByRole("textbox", { name: "Text" })).toHaveValue(
      "Collect at the barn.",
    );
  });

  it("closes only once the save is done, showing it is busy until then", async () => {
    let finishSave: () => void = () => {};
    const onSave = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          finishSave = resolve;
        }),
    );
    const { onClose } = renderEditor(onSave);

    await replaceText("Collect at the farm shop.");
    await userEvent.click(saveButton());

    expect(onSave).toHaveBeenCalledWith("Collect at the farm shop.");
    expect(saveButton()).toHaveClass("ant-btn-loading");
    expect(onClose).not.toHaveBeenCalled();

    finishSave();

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  });

  it("stays open with the text when the save fails, ready for another try", async () => {
    const onSave = vi
      .fn()
      .mockRejectedValueOnce(new Error("Network Error"))
      .mockResolvedValueOnce(undefined);
    const { onClose } = renderEditor(onSave);

    await replaceText("Collect at the farm shop.");
    await userEvent.click(saveButton());

    await waitFor(() => expect(saveButton()).not.toHaveClass("ant-btn-loading"));
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("textbox", { name: "Text" })).toHaveValue(
      "Collect at the farm shop.",
    );

    await userEvent.click(saveButton());

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(onSave).toHaveBeenLastCalledWith("Collect at the farm shop.");
  });

  it("closes right away when the save returns nothing to wait for", async () => {
    const onSave = vi.fn();
    const { onClose } = renderEditor(onSave);

    await userEvent.click(saveButton());

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(onSave).toHaveBeenCalledWith("Collect at the barn.");
  });

  it("closes from cancel without saving", async () => {
    const onSave = vi.fn();
    const { onClose } = renderEditor(onSave);

    await userEvent.click(screen.getByRole("button", { name: "common.cancel" }));

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onSave).not.toHaveBeenCalled();
  });

  it("refuses to save a text over the character limit", async () => {
    const onSave = vi.fn();
    renderEditor(onSave, { maxCharacters: 10 });

    await replaceText("Far too long for the box.");

    expect(saveButton()).toBeDisabled();
  });

  // A line ends at a paragraph or a break, so a heading or a list counts
  // towards the line that follows it.
  it.each([
    ["a footer column", FOOTER_COLUMN_HTML, 3, 35, 13],
    ["formatted instructions", INSTRUCTIONS_HTML, 2, 64, 37],
    ["the editing surface's HTML", EDITING_SURFACE_HTML, 2, 51, 31],
  ])(
    "counts the lines, characters and longest line of %s",
    (_label, value, lines, characters, longestLine) => {
      renderEditor(vi.fn(), {
        value,
        maxLines: 10,
        maxCharacters: 500,
        maxCharsPerLine: 100,
      });

      expect(
        screen.getByText(`common.lines: ${lines} / 10`),
      ).toBeInTheDocument();
      expect(
        screen.getByText(`common.characters: ${characters} / 500`),
      ).toBeInTheDocument();
      expect(
        screen.getByText(`common.longest_line: ${longestLine} / 100`),
      ).toBeInTheDocument();
    },
  );

  it("measures stored HTML without running anything in it", () => {
    const constructed = vi.fn();
    customElements.define(
      "stored-html-probe",
      class extends HTMLElement {
        constructor() {
          super();
          constructed();
        }
      },
    );

    renderEditor(vi.fn(), { value: HOSTILE_HTML, maxCharacters: 100 });

    expect(screen.getByText("common.characters: 8 / 100")).toBeInTheDocument();
    expect(constructed).not.toHaveBeenCalled();
  });

  it("never writes stored HTML into an element of the page", () => {
    const setInnerHtml = vi.spyOn(Element.prototype, "innerHTML", "set");

    renderEditor(vi.fn(), { value: HOSTILE_HTML, maxCharacters: 100 });

    expect(screen.getByText("common.characters: 8 / 100")).toBeInTheDocument();
    // AntD writes its CSS into the page's <style> elements this way.
    const pageWritesOfStoredHtml = setInnerHtml.mock.calls.filter(
      ([html], call) => {
        const element = setInnerHtml.mock.contexts[call];
        return (
          html.includes("Hi&nbsp;there") &&
          element instanceof Element &&
          element.ownerDocument === document
        );
      },
    );
    expect(pageWritesOfStoredHtml).toEqual([]);
  });
});
