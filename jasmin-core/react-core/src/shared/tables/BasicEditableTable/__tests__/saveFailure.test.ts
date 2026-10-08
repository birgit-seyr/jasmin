import { describe, expect, it, vi } from "vitest";

// The message comes from the server's body; the code lookup never matches here.
vi.mock("@shared/utils/apiError", () => ({
  getErrorMessage: (error: { response?: { data?: { message?: string } } }, fallback: string) =>
    error?.response?.data?.message ?? fallback,
}));

import { describeSaveFailure } from "../saveFailure";
import type { EditableColumnConfig } from "../types";

const columns: EditableColumnConfig[] = [
  { title: "Article", dataIndex: "share_article", inputType: "select" },
  { title: "Amount", dataIndex: "amount", inputType: "positive_decimal2" },
];

const refusal = (data: Record<string, unknown>) => ({
  isAxiosError: true,
  response: { status: 400, data },
});

describe("describeSaveFailure", () => {
  it("leads the banner with the titles of the columns at fault", () => {
    const failure = describeSaveFailure(
      refusal({ code: "validation_error", message: "Too big.", details: { amount: ["Too big."] } }),
      columns,
      "Save failed",
    );

    expect(failure.message).toBe("Amount: Too big.");
    expect(failure.fieldErrors).toEqual({ amount: "Too big." });
  });

  it.each([
    ["DRF's non-field key", "non_field_errors"],
    ["the canonical list key", "_errors"],
    ["Django's model-wide key", "__all__"],
  ])("shows a refusal under %s without a field prefix or a red border", (_label, key) => {
    const reason = "The fields year, share_article must make a unique set.";
    const failure = describeSaveFailure(
      refusal({ code: "validation_error", message: reason, details: { [key]: [reason] } }),
      columns,
      "Save failed",
    );

    expect(failure.message).toBe(reason);
    expect(failure.fieldErrors).toEqual({});
  });

  it("shows a top-level DRF non-field refusal without a prefix", () => {
    const reason = "Duplicate entry.";
    const failure = describeSaveFailure(
      refusal({ message: reason, non_field_errors: [reason] }),
      columns,
      "Save failed",
    );

    expect(failure.message).toBe(reason);
    expect(failure.fieldErrors).toEqual({});
  });
});
