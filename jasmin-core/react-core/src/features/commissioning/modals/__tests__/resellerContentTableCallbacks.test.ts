/**
 * The reseller content tables seed a new line with size M, unit KG and the
 * tenant's default tax rate, and stamp the parent document on every save.
 */
import type { FormInstance } from "antd";
import { describe, expect, it, vi } from "vitest";

import { makeContentCustomEdit, makeFkCustomSave } from "../resellerContentTableCallbacks";

const fakeForm = () =>
  ({ setFieldsValue: vi.fn() }) as unknown as FormInstance & {
    setFieldsValue: ReturnType<typeof vi.fn>;
  };

describe("makeContentCustomEdit", () => {
  it("seeds a new line with the defaults, in the form and the record", () => {
    const form = fakeForm();
    const record = makeContentCustomEdit(7)({ key: -1, note: "x" }, form);
    const defaults = { size: "M", unit: "KG", tax_rate: 7 };
    expect(form.setFieldsValue).toHaveBeenCalledWith(defaults);
    expect(record).toEqual({ key: -1, note: "x", ...defaults });
  });

  it("leaves a saved line alone", () => {
    const form = fakeForm();
    const saved = { key: "line-1", size: "L", unit: "PCS", tax_rate: 19 };
    expect(makeContentCustomEdit(7)(saved, form)).toBe(saved);
    expect(form.setFieldsValue).not.toHaveBeenCalled();
  });
});

describe("makeFkCustomSave", () => {
  it("stamps the parent document onto the row", () => {
    expect(makeFkCustomSave("invoice_id", "inv-1")({ amount: 2 })).toEqual({
      amount: 2,
      invoice_id: "inv-1",
    });
  });

  it("overrides a stale parent value on the row", () => {
    expect(
      makeFkCustomSave("delivery_note", "dn-2")({ delivery_note: "dn-1" }),
    ).toEqual({ delivery_note: "dn-2" });
  });
});
