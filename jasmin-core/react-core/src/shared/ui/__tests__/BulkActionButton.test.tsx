import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// vi.mock factories are hoisted to the top of the file, so any closed-over
// variable must be created via vi.hoisted() to survive the lift.
const { notify } = vi.hoisted(() => ({
  notify: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
  },
}));

vi.mock("@shared/utils", () => ({ notify }));

import i18n from "@shared/i18n";
import BulkActionButton from "../BulkActionButton";

beforeEach(() => {
  Object.values(notify).forEach((fn) => fn.mockReset());
});

describe("BulkActionButton", () => {
  it("is disabled when no rows are selected and refuses to call the API", async () => {
    const apiFunction = vi.fn().mockResolvedValue({});
    render(
      <BulkActionButton
        selectedIds={[]}
        apiFunction={apiFunction}
        buttonText="Delete"
      />,
    );

    const btn = screen.getByRole("button", { name: /delete/i });
    expect(btn).toBeDisabled();

    // Even if we force a click via userEvent, the disabled button does NOT fire.
    const user = userEvent.setup();
    await user.click(btn);
    expect(apiFunction).not.toHaveBeenCalled();
  });

  it("calls the apiFunction with { ids, ...payload }, fires success notify, clears selection and refreshes data", async () => {
    const apiFunction = vi.fn().mockResolvedValue({ ok: true });
    const refreshData = vi.fn().mockResolvedValue(undefined);
    const onClearSelection = vi.fn();
    const onSuccess = vi.fn();

    render(
      <BulkActionButton
        selectedIds={["a", "b"]}
        apiFunction={apiFunction}
        buttonText="Confirm"
        successMessage="Done!"
        payload={{ reason: "manual" }}
        onSuccess={onSuccess}
        onClearSelection={onClearSelection}
        refreshData={refreshData}
      />,
    );

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /confirm/i }));

    expect(apiFunction).toHaveBeenCalledTimes(1);
    expect(apiFunction).toHaveBeenCalledWith({
      ids: ["a", "b"],
      reason: "manual",
    });
    expect(notify.success).toHaveBeenCalledWith("Done!");
    expect(onSuccess).toHaveBeenCalledWith({ ok: true }, ["a", "b"]);
    expect(onClearSelection).toHaveBeenCalledTimes(1);
    expect(refreshData).toHaveBeenCalledTimes(1);
  });

  it("warns about the ids a partial-success body reports under `errors`", async () => {
    // A 207 resolves exactly like a 200, so the skipped ids only reach the
    // user if the resolved body is inspected.
    const apiFunction = vi.fn().mockResolvedValue({
      updated: 1,
      created: 0,
      errors: [{ id: "a", error: "Inventory entry already counted (70)" }],
    });
    const onSuccess = vi.fn();

    render(
      <BulkActionButton
        selectedIds={["a", "b"]}
        apiFunction={apiFunction}
        buttonText="Finalize"
        successMessage="Done!"
        onSuccess={onSuccess}
      />,
    );

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /finalize/i }));

    expect(notify.warning).toHaveBeenCalledTimes(1);
    expect(notify.warning.mock.calls[0][0]).toContain("already counted");
    // The warning replaces the green toast; the caller still refreshes.
    expect(notify.success).not.toHaveBeenCalled();
    expect(onSuccess).toHaveBeenCalledTimes(1);
  });

  async function clickWithSkips(errors: unknown[]) {
    const apiFunction = vi.fn().mockResolvedValue({ updated: 0, errors });
    render(
      <BulkActionButton
        selectedIds={["a", "b"]}
        apiFunction={apiFunction}
        buttonText="Finalize"
      />,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /finalize/i }));
  }

  it("names a skipped item's reason in its translated error code", async () => {
    await clickWithSkips([
      {
        id: "a",
        error: "This week is in the past.",
        code: "commissioning.past_week",
      },
    ]);

    expect(notify.warning).toHaveBeenCalledWith(
      i18n.t("table.bulk_partial_skipped", {
        skipped: 1,
        total: 2,
        reason: i18n.t("errors.commissioning.past_week"),
      }),
    );
    expect(notify.warning.mock.calls[0][0]).not.toContain(
      "This week is in the past.",
    );
  });

  it("keeps the server's reason when the code has no translation", async () => {
    await clickWithSkips([
      { id: "a", error: "Something odd happened", code: "no_such.code" },
    ]);

    expect(notify.warning.mock.calls[0][0]).toContain("Something odd happened");
  });

  it("asks for a selection in the user's language when clicked with none", async () => {
    const apiFunction = vi.fn().mockResolvedValue({});
    render(
      <BulkActionButton
        selectedIds={[]}
        apiFunction={apiFunction}
        buttonText="x"
        buttonProps={{ disabled: false }}
      />,
    );

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "x" }));

    const message = i18n.t("table.bulk_select_at_least_one");
    expect(message).not.toBe("table.bulk_select_at_least_one");
    expect(notify.warning).toHaveBeenCalledWith(message);
    expect(apiFunction).not.toHaveBeenCalled();
  });

  it("sends the selected ids as strings, the way model ids travel", async () => {
    const apiFunction = vi.fn().mockResolvedValue({});
    render(
      <BulkActionButton
        selectedIds={["a", 7]}
        apiFunction={apiFunction}
        buttonText="Run"
        payload={{ model: "invoice" }}
      />,
    );

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /run/i }));

    expect(apiFunction).toHaveBeenCalledWith({
      ids: ["a", "7"],
      model: "invoice",
    });
  });

  it("respects the confirmMessage — cancelling the prompt aborts the call", async () => {
    const apiFunction = vi.fn().mockResolvedValue({});
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);

    render(
      <BulkActionButton
        selectedIds={["a"]}
        apiFunction={apiFunction}
        buttonText="Delete"
        confirmMessage="Are you sure?"
      />,
    );

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /delete/i }));

    expect(confirmSpy).toHaveBeenCalledWith("Are you sure?");
    expect(apiFunction).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it("surfaces a friendly error notification when the API rejects", async () => {
    const apiFunction = vi.fn().mockRejectedValue({
      isAxiosError: true,
      response: { data: { message: "Cannot delete: in use" } },
    });
    const onError = vi.fn();
    // Silence the page's console.error.
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    render(
      <BulkActionButton
        selectedIds={["a"]}
        apiFunction={apiFunction}
        buttonText="Delete"
        onError={onError}
      />,
    );

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /delete/i }));

    expect(notify.error).toHaveBeenCalledTimes(1);
    expect(notify.error).toHaveBeenCalledWith("Cannot delete: in use");
    expect(onError).toHaveBeenCalledTimes(1);
    errSpy.mockRestore();
  });

  it("uses the custom errorMessage prop verbatim when provided (overrides extracted message)", async () => {
    const apiFunction = vi.fn().mockRejectedValue(new Error("boom"));
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    render(
      <BulkActionButton
        selectedIds={["a"]}
        apiFunction={apiFunction}
        buttonText="Delete"
        errorMessage="Could not delete the selected rows."
      />,
    );

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /delete/i }));

    expect(notify.error).toHaveBeenCalledWith(
      "Could not delete the selected rows.",
    );
    errSpy.mockRestore();
  });
});
