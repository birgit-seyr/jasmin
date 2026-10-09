/**
 * A station day's pickup info cell: the office gets an edit button, every
 * other role the text read-only in a dialog (sanitised), and nothing when the
 * day has no pickup info.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) => (typeof fallback === "string" ? fallback : key),
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

import StationDayPickupInfoCell from "../StationDayPickupInfoCell";

const INFO = "<p>Schlüssel liegt <strong>unter der Matte</strong></p>";
const TITLE = "Hof - Dienstag";

function renderCell(props: Partial<React.ComponentProps<typeof StationDayPickupInfoCell>> = {}) {
  const onEdit = vi.fn();
  const view = render(
    <StationDayPickupInfoCell html={INFO} title={TITLE} canEdit={false} onEdit={onEdit} {...props} />,
  );
  return { onEdit, ...view };
}

describe("StationDayPickupInfoCell for the office", () => {
  it("offers an edit button that opens the editor", async () => {
    const { onEdit } = renderCell({ canEdit: true });

    await userEvent.click(screen.getByRole("button", { name: "table.edit" }));

    expect(onEdit).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "common.view" })).toBeNull();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it.each([null, undefined, ""])("offers the edit button also for a day without info (%s)", (html) => {
    renderCell({ canEdit: true, html });

    expect(screen.getByRole("button", { name: "table.edit" })).toBeInTheDocument();
  });
});

describe("StationDayPickupInfoCell read-only", () => {
  it.each([null, undefined, ""])("shows nothing for a day without info (%s)", (html) => {
    const { container } = renderCell({ html });

    expect(container).toBeEmptyDOMElement();
  });

  it("shows the info in a titled dialog and closes it again", async () => {
    const { onEdit } = renderCell();
    expect(screen.queryByRole("button", { name: "table.edit" })).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "common.view" }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(TITLE)).toBeInTheDocument();
    expect(within(dialog).getByText("unter der Matte").tagName).toBe("STRONG");
    expect(onEdit).not.toHaveBeenCalled();

    await userEvent.click(within(dialog).getByRole("button", { name: "common.close" }));
    await waitFor(() => expect(screen.queryByText("unter der Matte")).not.toBeVisible());
  });

  it("strips scripts and event handlers from the info", async () => {
    const malicious =
      '<p>Abholung ab 16 Uhr</p><img src="x" onerror="window.__pwned = true"><script>window.__pwned = true</script>' +
      '<a href="javascript:window.__pwned=true">Link</a>';
    renderCell({ html: malicious });

    await userEvent.click(screen.getByRole("button", { name: "common.view" }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Abholung ab 16 Uhr")).toBeInTheDocument();
    expect(dialog.querySelector("script")).toBeNull();
    expect(dialog.querySelector("img")?.getAttribute("onerror")).toBeNull();
    expect(within(dialog).getByText("Link").getAttribute("href")).toBeNull();
    expect((window as { __pwned?: boolean }).__pwned).toBeUndefined();
  });

  it("puts the dialog on the layer it is given", async () => {
    renderCell({ zIndex: 1500 });

    await userEvent.click(screen.getByRole("button", { name: "common.view" }));

    await screen.findByRole("dialog");
    expect(document.querySelector<HTMLElement>(".ant-modal-wrap")?.style.zIndex).toBe("1500");
  });
});
