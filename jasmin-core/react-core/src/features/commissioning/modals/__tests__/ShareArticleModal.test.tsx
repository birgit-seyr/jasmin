/**
 * ShareArticleModal: the dialog a page opens to add a share article on the
 * spot — its name, unit, description, whether it is active and bought in, and
 * which harvest share it goes into. Rendered the way every page hosts it:
 * mounted closed with the page, opened from a button, and closed again by the
 * page when the dialog reports a save or a cancel. The real modal, its form
 * hook and the unit and share-option hooks render; the generated commissioning
 * client is the mocking boundary, its share-option hook a real TanStack query
 * around a spy, and the toasts are recorded.
 *
 * Nothing in the dialog reads today's date, so the clock runs free.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ActiveShareOptions, ShareArticle } from "@shared/api/generated/models";
import germanErrors from "@shared/i18n/locales/de/errors.json";
import { flushMicrotasks, profileRenders, type ProfileRendersHandle } from "@/test/profileRenders";

// One `t` for every render, as react-i18next keeps it.
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

const notify = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("@shared/utils/notify", () => ({
  default: notify,
  registerAnnouncer: () => {},
  announcePolite: () => {},
}));

const api = vi.hoisted(() => ({
  activeShareOptions: vi.fn<() => Promise<ActiveShareOptions>>(),
  createArticle: vi.fn<(article: Record<string, unknown>) => Promise<ShareArticle>>(),
}));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  return {
    useCommissioningShareOptionsActiveRetrieve: () =>
      useQuery({
        queryKey: ["/api/commissioning/share_options/active/"],
        queryFn: () => api.activeShareOptions(),
      }),
    commissioningShareArticlesCreate: (article: Record<string, unknown>) =>
      api.createArticle(article),
  };
});

import ShareArticleModal from "../ShareArticleModal";

// ── Fixtures ────────────────────────────────────────────────────────────────

const SHARE_OPTIONS_TOGETHER: ActiveShareOptions = {
  HARVEST_SHARE: true, HARVEST_SHARE_FRUIT: false, CHICKEN_SHARE: false, HONEY_SHARE: false,
  OIL_SHARE: false, GRAIN_SHARE: false, BREAD_SHARE: false, fruit_and_veg_shares_are_separate: false,
};
// The farm runs a vegetable share and a fruit share of its own.
const SHARE_OPTIONS_APART: ActiveShareOptions = {
  ...SHARE_OPTIONS_TOGETHER, HARVEST_SHARE_FRUIT: true, fruit_and_veg_shares_are_separate: true,
};

// What the dialog appends to the name of an article the farm buys in.
const PURCHASED_SUFFIX = "commissioning.purchased_name_suffix";

// Labels, as the mocked `t` returns them.
const TITLE = "commissioning.add_share_article";
const NAME = "commissioning.name";
const UNIT = "commissioning.default_movement_unit";
const DESCRIPTION = "commissioning.description";
const ACTIVE = "commissioning.is_active";
const PURCHASED = "commissioning.is_purchased";
const HARVEST_SHARE = "commissioning.for_harvest_share";
const VEGETABLE_SHARE = "commissioning.for_harvest_share_veg_only";
const FRUIT_SHARE = "commissioning.for_harvest_share_fruits_only";
const KG = "commissioning.units.kg";
const PIECES = "commissioning.units.pcs";
const BUNCH = "commissioning.units.bunch";

let createdCount = 0;

/** A rejected request as axios hands it over, carrying the server's body. */
const httpError = (status: number, data: Record<string, unknown>) =>
  Object.assign(new Error(`Request failed with status code ${status}`), {
    isAxiosError: true,
    response: { status, data },
  });

beforeEach(() => {
  createdCount = 0;
  notify.success.mockReset();
  notify.error.mockReset();
  api.activeShareOptions.mockReset().mockResolvedValue(SHARE_OPTIONS_TOGETHER);
  // The backend answers with the saved article, its options spread over the
  // three share-option fields.
  api.createArticle.mockReset().mockImplementation(async (body) => {
    createdCount += 1;
    const { share_option_list: options = [], ...fields } = body as Record<string, unknown> & {
      share_option_list?: string[];
    };
    return {
      ...fields,
      id: `article-new-${createdCount}`,
      share_option: options[0] ?? null,
      share_option2: options[1] ?? null,
      share_option3: options[2] ?? null,
    } as ShareArticle;
  });
});

// ── Helpers ─────────────────────────────────────────────────────────────────

const OPEN_DIALOG = "Add an article";

/** A page hosting the dialog: a button opens it, and a save or a cancel closes it. */
function ArticlePage({
  defaultValues,
  onSuccess,
  onClose,
  profiler,
}: {
  defaultValues?: Record<string, unknown>;
  onSuccess: (saved: Record<string, unknown>) => void;
  onClose: () => void;
  profiler: ProfileRendersHandle;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        {OPEN_DIALOG}
      </button>
      {profiler.wrap(
        <ShareArticleModal
          isOpen={open}
          onClose={() => {
            onClose();
            setOpen(false);
          }}
          onSuccess={(saved) => {
            onSuccess(saved);
            setOpen(false);
          }}
          // A fresh object on every render, as the pages pass it.
          defaultValues={defaultValues ? { ...defaultValues } : undefined}
        />,
      )}
    </>
  );
}

let queryClient: QueryClient;

/** Renders the page and waits until the farm's share options are in. */
async function renderPage(defaultValues?: Record<string, unknown>) {
  const user = userEvent.setup();
  const onSuccess = vi.fn();
  const onClose = vi.fn();
  const profiler = profileRenders();
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ArticlePage
        defaultValues={defaultValues}
        onSuccess={onSuccess}
        onClose={onClose}
        profiler={profiler}
      />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(api.activeShareOptions).toHaveBeenCalled());
  await waitFor(() => expect(queryClient.isFetching()).toBe(0));
  return { user, onSuccess, onClose, profiler };
}

type User = ReturnType<typeof userEvent.setup>;

const dialog = () => screen.getByRole("dialog");
const queryDialog = () => screen.queryByRole("dialog");

async function openDialog(user: User) {
  await user.click(screen.getByRole("button", { name: OPEN_DIALOG }));
  return screen.findByRole("dialog");
}

const nameInput = () => within(dialog()).getByRole("textbox", { name: NAME });
const descriptionInput = () => within(dialog()).getByRole("textbox", { name: DESCRIPTION });
const unitSelect = () => within(dialog()).getByRole("combobox", { name: UNIT });
// The OK button carries a spinner icon, and its name, while it saves.
const saveButton = () => within(dialog()).getByRole("button", { name: /table\.save/ });
const cancelButton = () => within(dialog()).getByRole("button", { name: "table.cancel" });

/** The checkbox in the dialog whose text reads `text`; the text sits beside it. */
function checkboxBeside(text: string): HTMLInputElement {
  const row = within(dialog()).getByText(text).parentElement;
  if (!row) throw new Error(`No checkbox beside ${text}`);
  return within(row).getByRole("checkbox");
}

const shownCheckboxTexts = () =>
  [ACTIVE, PURCHASED, HARVEST_SHARE, VEGETABLE_SHARE, FRUIT_SHARE].filter(
    (text) => within(dialog()).queryByText(text) !== null,
  );

async function setChecked(user: User, text: string, checked: boolean) {
  const checkbox = checkboxBeside(text);
  if (checkbox.checked !== checked) await user.click(checkbox);
  expect(checkbox.checked).toBe(checked);
}

function openDropdown(): HTMLElement {
  const dropdown = Array.from(document.querySelectorAll<HTMLElement>(".ant-select-dropdown"))
    .filter((each) => !each.classList.contains("ant-select-dropdown-hidden"))
    .pop();
  if (!dropdown) throw new Error("No select is open");
  return dropdown;
}

async function unitOptions(user: User): Promise<string[]> {
  await user.click(unitSelect());
  const dropdown = await waitFor(openDropdown);
  return Array.from(dropdown.querySelectorAll(".ant-select-item-option-content")).map(
    (option) => option.textContent ?? "",
  );
}

async function pickUnit(user: User, unit: string) {
  await user.click(unitSelect());
  await user.click(within(await waitFor(openDropdown)).getByText(unit));
}

/** The label the unit select shows for its current value. */
const shownUnit = () =>
  unitSelect().closest(".ant-select")?.querySelector(".ant-select-selection-item")?.textContent ??
  "";

async function fillArticle(user: User, name: string, unit: string) {
  await user.type(nameInput(), name);
  await pickUnit(user, unit);
}

const sentArticle = () => api.createArticle.mock.lastCall?.[0];
const createdOnce = () => waitFor(() => expect(api.createArticle).toHaveBeenCalledTimes(1));
const dialogClosed = () => waitFor(() => expect(queryDialog()).not.toBeInTheDocument());

// ── Opening ─────────────────────────────────────────────────────────────────

describe("ShareArticleModal opening", () => {
  it("stays closed until the page opens it", async () => {
    await renderPage();

    expect(queryDialog()).not.toBeInTheDocument();
    expect(api.createArticle).not.toHaveBeenCalled();
  });

  it("starts an active article without a name or unit, in the harvest share", async () => {
    const { user } = await renderPage();

    await openDialog(user);

    expect(within(dialog()).getByText(TITLE)).toBeInTheDocument();
    expect(nameInput()).toHaveValue("");
    expect(descriptionInput()).toHaveValue("");
    expect(shownUnit()).toBe("");
    expect(checkboxBeside(ACTIVE)).toBeChecked();
    expect(checkboxBeside(PURCHASED)).not.toBeChecked();
    expect(checkboxBeside(HARVEST_SHARE)).toBeChecked();
    expect(shownCheckboxTexts()).toEqual([ACTIVE, PURCHASED, HARVEST_SHARE]);
  });

  it("offers the units kg, pieces and bunch", async () => {
    const { user } = await renderPage();
    await openDialog(user);

    expect(await unitOptions(user)).toEqual([KG, PIECES, BUNCH]);
  });

  it("starts with the values the page hands it", async () => {
    const { user } = await renderPage({ is_purchased: true });

    await openDialog(user);

    expect(checkboxBeside(PURCHASED)).toBeChecked();
    expect(checkboxBeside(ACTIVE)).toBeChecked();
    expect(checkboxBeside(HARVEST_SHARE)).toBeChecked();
  });

  it("offers the vegetable and the fruit share apart when the farm runs them apart", async () => {
    api.activeShareOptions.mockResolvedValue(SHARE_OPTIONS_APART);
    const { user } = await renderPage();

    await openDialog(user);

    expect(shownCheckboxTexts()).toEqual([ACTIVE, PURCHASED, VEGETABLE_SHARE, FRUIT_SHARE]);
  });

  it("settles after opening instead of re-rendering in a loop", async () => {
    const { user, profiler } = await renderPage({ is_purchased: true });
    await openDialog(user);
    await flushMicrotasks();

    expect(profiler.onRender.mock.calls.length).toBeLessThan(120);
  });
});

// ── Saving ──────────────────────────────────────────────────────────────────

describe("ShareArticleModal saving", () => {
  it("creates the article as typed, in the harvest share, and hands the saved article to the page", async () => {
    const { user, onSuccess, onClose } = await renderPage();
    await openDialog(user);

    await fillArticle(user, "Kohlrabi", PIECES);
    await user.type(descriptionInput(), "Purple, with leaves");
    await user.click(saveButton());

    await createdOnce();
    expect(sentArticle()).toEqual({
      name: "Kohlrabi",
      default_movement_unit: "PCS",
      description: "Purple, with leaves",
      is_active: true,
      is_purchased: false,
      harvest_share: true,
      share_option_list: ["HARVEST_SHARE"],
    });
    await dialogClosed();
    expect(onSuccess).toHaveBeenCalledTimes(1);
    expect(onSuccess).toHaveBeenCalledWith(
      expect.objectContaining({ id: "article-new-1", name: "Kohlrabi", share_option: "HARVEST_SHARE" }),
    );
    expect(notify.error).not.toHaveBeenCalled();
    // The page hears of the close, and nothing is saved twice.
    expect(onClose).toHaveBeenCalled();
    expect(api.createArticle).toHaveBeenCalledTimes(1);
  });

  it("saves an inactive article outside every share when the office unticks them", async () => {
    const { user } = await renderPage();
    await openDialog(user);

    await fillArticle(user, "Seed potatoes", KG);
    await setChecked(user, ACTIVE, false);
    await setChecked(user, HARVEST_SHARE, false);
    await user.click(saveButton());

    await createdOnce();
    expect(sentArticle()).toMatchObject({
      name: "Seed potatoes",
      default_movement_unit: "KG",
      is_active: false,
      harvest_share: false,
      share_option_list: [],
    });
  });

  it("marks a bought-in article in its name", async () => {
    const { user, onSuccess } = await renderPage();
    await openDialog(user);

    await fillArticle(user, "Lemons", KG);
    await setChecked(user, PURCHASED, true);
    await user.click(saveButton());

    await createdOnce();
    expect(sentArticle()).toMatchObject({ name: `Lemons ${PURCHASED_SUFFIX}`, is_purchased: true });
    await waitFor(() =>
      expect(onSuccess).toHaveBeenCalledWith(
        expect.objectContaining({ name: `Lemons ${PURCHASED_SUFFIX}`, is_purchased: true }),
      ),
    );
  });

  it("marks a bought-in article once when the page starts it as bought in", async () => {
    const { user } = await renderPage({ is_purchased: true });
    await openDialog(user);

    await fillArticle(user, `Oranges ${PURCHASED_SUFFIX}`, PIECES);
    await user.click(saveButton());

    await createdOnce();
    expect(sentArticle()).toMatchObject({ name: `Oranges ${PURCHASED_SUFFIX}`, is_purchased: true });
  });

  it("takes an article named as bought in for a bought-in one", async () => {
    const { user } = await renderPage();
    await openDialog(user);

    await fillArticle(user, `Bananas ${PURCHASED_SUFFIX}`, BUNCH);
    await user.click(saveButton());

    await createdOnce();
    expect(sentArticle()).toMatchObject({
      name: `Bananas ${PURCHASED_SUFFIX}`,
      default_movement_unit: "BUNCH",
      is_purchased: true,
    });
  });

  it.each([
    ["the vegetable share", true, false, ["HARVEST_SHARE"]],
    ["the fruit share", false, true, ["HARVEST_SHARE_FRUIT"]],
    ["both shares", true, true, ["HARVEST_SHARE", "HARVEST_SHARE_FRUIT"]],
    ["neither share", false, false, []],
  ])(
    "puts the article into %s when the farm runs them apart",
    async (_shares, vegetables, fruit, options) => {
      api.activeShareOptions.mockResolvedValue(SHARE_OPTIONS_APART);
      const { user } = await renderPage();
      await openDialog(user);

      await fillArticle(user, "Rhubarb", KG);
      await setChecked(user, VEGETABLE_SHARE, vegetables);
      await setChecked(user, FRUIT_SHARE, fruit);
      await user.click(saveButton());

      await createdOnce();
      expect(sentArticle()).toMatchObject({
        harvest_share: vegetables,
        harvest_share_fruit: fruit,
        share_option_list: options,
      });
    },
  );

  it("saves with the Enter key", async () => {
    const { user, onSuccess } = await renderPage();
    await openDialog(user);
    await fillArticle(user, "Kale", BUNCH);

    await user.type(nameInput(), "{Enter}");

    await createdOnce();
    expect(sentArticle()).toMatchObject({ name: "Kale", default_movement_unit: "BUNCH" });
    await dialogClosed();
    expect(onSuccess).toHaveBeenCalledTimes(1);
  });

  it("saves once when Enter is pressed again while the save runs", async () => {
    let answer: (article: ShareArticle) => void = () => {};
    api.createArticle.mockImplementation(() => new Promise((resolve) => (answer = resolve)));
    const { user, onSuccess } = await renderPage();
    await openDialog(user);
    await fillArticle(user, "Kale", BUNCH);

    await user.type(nameInput(), "{Enter}");
    await createdOnce();
    await user.type(nameInput(), "{Enter}{Enter}");

    expect(api.createArticle).toHaveBeenCalledTimes(1);
    answer({ id: "article-kale", name: "Kale", default_movement_unit: "BUNCH" });
    await dialogClosed();
    expect(api.createArticle).toHaveBeenCalledTimes(1);
    expect(onSuccess).toHaveBeenCalledTimes(1);
  });

  it("shows that it saves until the server answers", async () => {
    let answer: (article: ShareArticle) => void = () => {};
    api.createArticle.mockImplementation(() => new Promise((resolve) => (answer = resolve)));
    const { user, onSuccess } = await renderPage();
    await openDialog(user);
    await fillArticle(user, "Kale", BUNCH);

    await user.click(saveButton());

    await waitFor(() => expect(saveButton()).toHaveClass("ant-btn-loading"));
    expect(onSuccess).not.toHaveBeenCalled();
    answer({ id: "article-kale", name: "Kale", default_movement_unit: "BUNCH" });
    await dialogClosed();
    expect(onSuccess).toHaveBeenCalledWith(expect.objectContaining({ id: "article-kale" }));
  });

  it("opens empty again for the next article after a save", async () => {
    const { user } = await renderPage();
    await openDialog(user);
    await fillArticle(user, "Kale", BUNCH);
    await setChecked(user, PURCHASED, true);
    await user.click(saveButton());
    await dialogClosed();

    await openDialog(user);

    expect(nameInput()).toHaveValue("");
    expect(shownUnit()).toBe("");
    expect(checkboxBeside(PURCHASED)).not.toBeChecked();
    expect(checkboxBeside(ACTIVE)).toBeChecked();
    expect(checkboxBeside(HARVEST_SHARE)).toBeChecked();
  });
});

// ── Refusals ────────────────────────────────────────────────────────────────

describe("ShareArticleModal refusals", () => {
  it("refuses an article without a name and a unit, saying why, and stays open", async () => {
    const { user, onSuccess, onClose } = await renderPage();
    await openDialog(user);

    await user.click(saveButton());

    expect(await within(dialog()).findByText("commissioning.please_enter_a_name")).toBeVisible();
    expect(within(dialog()).getByText("commissioning.please_select_a_unit")).toBeVisible();
    expect(nameInput()).toHaveAttribute("aria-invalid", "true");
    expect(api.createArticle).not.toHaveBeenCalled();
    expect(notify.error).not.toHaveBeenCalled();
    expect(onSuccess).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
    expect(dialog()).toBeInTheDocument();
  });

  it("refuses an article without a unit and saves it once the unit is picked", async () => {
    const { user } = await renderPage();
    await openDialog(user);
    await user.type(nameInput(), "Kale");

    await user.click(saveButton());

    expect(await within(dialog()).findByText("commissioning.please_select_a_unit")).toBeVisible();
    expect(within(dialog()).queryByText("commissioning.please_enter_a_name")).not.toBeInTheDocument();
    expect(api.createArticle).not.toHaveBeenCalled();

    await pickUnit(user, KG);
    await user.click(saveButton());

    await createdOnce();
    expect(sentArticle()).toMatchObject({ name: "Kale", default_movement_unit: "KG" });
  });

  it("shows the server's reason for a refused save and keeps the dialog open with what was typed", async () => {
    const message = "Ensure this field has no more than 100 characters.";
    api.createArticle.mockRejectedValue(
      httpError(400, { code: "validation_error", message, field: "name", details: { name: [message] } }),
    );
    const { user, onSuccess, onClose } = await renderPage();
    await openDialog(user);
    await fillArticle(user, "Kale", BUNCH);

    await user.click(saveButton());

    await waitFor(() => expect(notify.error).toHaveBeenCalledWith(message));
    expect(dialog()).toBeInTheDocument();
    expect(nameInput()).toHaveValue("Kale");
    expect(shownUnit()).toBe(BUNCH);
    await waitFor(() => expect(saveButton()).not.toHaveClass("ant-btn-loading"));
    expect(onSuccess).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
    expect(notify.success).not.toHaveBeenCalled();
  });

  it("shows a refusal with a known code in the office's words", async () => {
    api.createArticle.mockRejectedValue(
      httpError(400, {
        code: "share_article.invalid_share_option",
        message: "Invalid share options: ['HARVEST_SHARE']",
        field: "share_option_list",
      }),
    );
    const { user } = await renderPage();
    await openDialog(user);
    await fillArticle(user, "Kale", BUNCH);

    await user.click(saveButton());

    await waitFor(() =>
      expect(notify.error).toHaveBeenCalledWith(germanErrors.share_article.invalid_share_option),
    );
    expect(dialog()).toBeInTheDocument();
  });

  it("saves what was typed once the server takes it after a refusal", async () => {
    api.createArticle.mockRejectedValueOnce(httpError(503, { message: "Service unavailable" }));
    const { user, onSuccess } = await renderPage();
    await openDialog(user);
    await fillArticle(user, "Kale", BUNCH);
    await user.click(saveButton());
    await waitFor(() => expect(notify.error).toHaveBeenCalledWith("Service unavailable"));

    await user.click(saveButton());

    await waitFor(() => expect(api.createArticle).toHaveBeenCalledTimes(2));
    expect(api.createArticle.mock.calls[1][0]).toEqual(api.createArticle.mock.calls[0][0]);
    await dialogClosed();
    expect(onSuccess).toHaveBeenCalledTimes(1);
  });
});

// ── Cancelling ──────────────────────────────────────────────────────────────

describe("ShareArticleModal cancelling", () => {
  it("closes without saving and forgets what was typed", async () => {
    const { user, onClose, onSuccess } = await renderPage();
    await openDialog(user);
    await fillArticle(user, "Kale", BUNCH);
    await setChecked(user, ACTIVE, false);

    await user.click(cancelButton());

    await dialogClosed();
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onSuccess).not.toHaveBeenCalled();
    expect(api.createArticle).not.toHaveBeenCalled();

    await openDialog(user);

    expect(nameInput()).toHaveValue("");
    expect(shownUnit()).toBe("");
    expect(checkboxBeside(ACTIVE)).toBeChecked();
  });

  it("closes from its close icon without saving", async () => {
    const { user, onClose } = await renderPage();
    await openDialog(user);
    await fillArticle(user, "Kale", BUNCH);

    await user.click(within(dialog()).getByRole("button", { name: "Close" }));

    await dialogClosed();
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(api.createArticle).not.toHaveBeenCalled();
  });

  it("forgets the refused errors when it opens again", async () => {
    const { user } = await renderPage();
    await openDialog(user);
    await user.click(saveButton());
    await within(dialog()).findByText("commissioning.please_enter_a_name");

    await user.click(cancelButton());
    await dialogClosed();
    await openDialog(user);

    expect(within(dialog()).queryByText("commissioning.please_enter_a_name")).not.toBeInTheDocument();
    expect(nameInput()).not.toHaveAttribute("aria-invalid", "true");
  });
});
