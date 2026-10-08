/**
 * ``CsvColumnsTable``: the help table an import dialog shows for the columns
 * its CSV takes — each column's header, whether it is required and what it
 * means — one row per header.
 */

import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

import CsvColumnsTable from "../CsvColumnsTable";

describe("CsvColumnsTable", () => {
  it("lists each column with its header, whether it is required and its meaning, keyed by its header", () => {
    render(
      <CsvColumnsTable
        rows={[
          { field: "member_number", required: true, meaning: "The member's number" },
          { field: "note", required: false, meaning: "Anything else" },
        ]}
      />,
    );

    expect(
      screen.getAllByRole("columnheader").map((header) => header.textContent),
    ).toEqual(["csv_upload.col_field", "csv_upload.col_required", "csv_upload.col_meaning"]);
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows.map((row) => row.getAttribute("data-row-key"))).toEqual(["member_number", "note"]);
    expect(
      rows.map((row) => within(row).getAllByRole("cell").map((cell) => cell.textContent)),
    ).toEqual([
      ["member_number", "common.yes", "The member's number"],
      ["note", "common.no", "Anything else"],
    ]);
    expect(within(rows[0]).getByText("member_number").tagName).toBe("CODE");
  });
});
