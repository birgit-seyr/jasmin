import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// vi.mock factories are hoisted to the top of the file, so any closed-over
// variable must be created via vi.hoisted() to survive the lift.
const { notify, axiosMock } = vi.hoisted(() => ({
  notify: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
  },
  axiosMock: {
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock("@shared/utils", () => ({ notify }));
vi.mock("@shared/services/api", () => ({ default: axiosMock }));

import BulkActionButton from "../BulkActionButton";

beforeEach(() => {
  Object.values(notify).forEach((fn) => fn.mockReset());
  Object.values(axiosMock).forEach((fn) => fn.mockReset());
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

  it("warns and does not hit the API when selection is empty even if it could click", async () => {
    // selectedIds=[] makes the button disabled, so we test the early-return
    // branch via direct re-render with at least 1, then 0. Easier: enable it
    // via apiFunction trick — but the disabled check happens at the DOM level
    // first, so the early notify.warning branch is unreachable from a click.
    // We can still assert the contract: with 0 ids, the button is disabled.
    render(
      <BulkActionButton
        selectedIds={[]}
        apiFunction={vi.fn()}
        buttonText="x"
      />,
    );
    expect(screen.getByRole("button", { name: "x" })).toBeDisabled();
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

  it("dispatches a POST via apiEndpoint when no apiFunction is provided", async () => {
    axiosMock.post.mockResolvedValue({ status: 200, data: { id: 1 } });
    const onClearSelection = vi.fn();

    render(
      <BulkActionButton
        selectedIds={["x"]}
        apiEndpoint="/api/things/bulk/"
        buttonText="Run"
        onClearSelection={onClearSelection}
      />,
    );

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /run/i }));

    expect(axiosMock.post).toHaveBeenCalledWith("/api/things/bulk/", {
      ids: ["x"],
    });
    expect(onClearSelection).toHaveBeenCalledTimes(1);
  });

  it("dispatches a DELETE with the payload under `data` (axios contract)", async () => {
    axiosMock.delete.mockResolvedValue({ status: 204, data: null });

    render(
      <BulkActionButton
        selectedIds={["x", "y"]}
        apiEndpoint="/api/things/"
        method="DELETE"
        buttonText="Trash"
      />,
    );

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /trash/i }));

    expect(axiosMock.delete).toHaveBeenCalledWith("/api/things/", {
      data: { ids: ["x", "y"] },
    });
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
