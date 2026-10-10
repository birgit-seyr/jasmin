/**
 * useShareArticleModal: the add-article dialog starts a new article in the
 * vegetable share when the farm runs one (none otherwise, so the office
 * picks), lets the page's own defaults win, and saves the ticked shares as
 * the article's share options with the purchased flag and name in step.
 */
import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Checkbox, Form, Input } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => (key === "commissioning.purchased_name_suffix" ? "Purchased" : key),
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

const api = vi.hoisted(() => ({
  activeShareOptions: {} as Record<string, unknown>,
  create: vi.fn(),
}));

vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  useCommissioningShareOptionsActiveRetrieve: () => ({
    data: api.activeShareOptions,
    isLoading: false,
  }),
  commissioningShareArticlesCreate: api.create,
}));

import { useShareArticleModal } from "../useShareArticleModal";

type ModalApi = ReturnType<typeof useShareArticleModal>;
let modal: ModalApi;

function Harness({ onSaved }: { onSaved?: (data: unknown) => void }) {
  modal = useShareArticleModal();
  return (
    <Form form={modal.form}>
      <Form.Item name="name">
        <Input aria-label="name" />
      </Form.Item>
      <Form.Item name="is_purchased" valuePropName="checked">
        <Checkbox>is_purchased</Checkbox>
      </Form.Item>
      <Form.Item name="harvest_share" valuePropName="checked">
        <Checkbox>harvest_share</Checkbox>
      </Form.Item>
      <Form.Item name="harvest_share_fruit" valuePropName="checked">
        <Checkbox>harvest_share_fruit</Checkbox>
      </Form.Item>
      <Form.Item name="is_active" valuePropName="checked">
        <Checkbox>is_active</Checkbox>
      </Form.Item>
      <button type="button" onClick={() => modal.saveShareArticle(onSaved)}>
        save
      </button>
    </Form>
  );
}

beforeEach(() => {
  api.activeShareOptions = { HARVEST_SHARE: true, fruit_and_veg_shares_are_separate: true };
  api.create.mockReset();
  api.create.mockImplementation(async (body: unknown) => ({ id: "new", ...(body as object) }));
});

describe("useShareArticleModal", () => {
  it("starts a new article active and in the vegetable share", () => {
    render(<Harness />);
    act(() => modal.openModal());
    expect(modal.isVisible).toBe(true);
    expect(modal.form.getFieldsValue(true)).toMatchObject({
      harvest_share: true,
      harvest_share_fruit: false,
      is_active: true,
    });
    expect(modal.fruit_and_veg_shares_are_separate).toBe(true);
  });

  it("starts a new article in no share when the farm runs no vegetable share", () => {
    api.activeShareOptions = {};
    render(<Harness />);
    act(() => modal.openModal());
    expect(modal.form.getFieldsValue(true)).toMatchObject({
      harvest_share: false,
      harvest_share_fruit: false,
    });
    expect(modal.fruit_and_veg_shares_are_separate).toBe(false);
  });

  it("lets the page's defaults win", () => {
    render(<Harness />);
    act(() => modal.openModal({ harvest_share: false, harvest_share_fruit: true, name: "Apples" }));
    expect(modal.form.getFieldsValue(true)).toMatchObject({
      harvest_share: false,
      harvest_share_fruit: true,
      name: "Apples",
    });
  });

  it("saves the ticked shares as share options and marks the name purchased", async () => {
    const onSaved = vi.fn();
    render(<Harness onSaved={onSaved} />);
    act(() => modal.openModal({ name: "Lemons", is_purchased: true, harvest_share_fruit: true }));

    await userEvent.click(screen.getByRole("button", { name: "save" }));

    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1));
    expect(api.create.mock.calls[0][0]).toMatchObject({
      name: "Lemons Purchased",
      is_purchased: true,
      share_option_list: ["HARVEST_SHARE", "HARVEST_SHARE_FRUIT"],
    });
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(expect.objectContaining({ id: "new" })));
    expect(modal.isVisible).toBe(false);
  });

  it("marks an article purchased when its name carries the suffix", async () => {
    render(<Harness />);
    act(() => modal.openModal({ name: "Lemons Purchased" }));
    await userEvent.click(screen.getByRole("button", { name: "save" }));
    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1));
    expect(api.create.mock.calls[0][0]).toMatchObject({ is_purchased: true });
  });

  it("closes and clears the form", () => {
    const { result } = renderHook(() => useShareArticleModal());
    act(() => result.current.openModal({ name: "Kale" }));
    act(() => result.current.closeModal());
    expect(result.current.isVisible).toBe(false);
    expect(result.current.form.getFieldsValue(true).name).toBeUndefined();
  });
});
