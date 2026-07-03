/**
 * Reconciliation behavior of BaseEntitySelector — the "don't spring back"
 * mechanism every multi-selector page relies on.
 *
 * The logic under test is the auto-select / preserve useEffect; the rendered
 * antd Select is irrelevant to it, so we stub Select to keep the test fast
 * and free of jsdom/antd layout quirks.
 */
import { render, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("antd", () => ({
  Select: () => null,
}));

import BaseEntitySelector, { type SelectorOption } from "../BaseEntitySelector";

const OPTS: SelectorOption<string>[] = [
  { value: "a", label: "A" },
  { value: "b", label: "B" },
];

describe("BaseEntitySelector — preserveSelection reconciliation", () => {
  it("auto-picks the first option when the value is empty", async () => {
    const onValueChange = vi.fn();
    render(
      <BaseEntitySelector
        value={null}
        onValueChange={onValueChange}
        options={OPTS}
        preserveSelection
      />,
    );
    await waitFor(() => expect(onValueChange).toHaveBeenCalledWith("a"));
  });

  it("KEEPS a still-valid value when the options change (no spring-back)", async () => {
    const onValueChange = vi.fn();
    const { rerender } = render(
      <BaseEntitySelector
        value="b"
        onValueChange={onValueChange}
        options={OPTS}
        preserveSelection
      />,
    );
    // New option set (different parent filter) — "b" is still offered.
    rerender(
      <BaseEntitySelector
        value="b"
        onValueChange={onValueChange}
        options={[
          { value: "b", label: "B" },
          { value: "c", label: "C" },
        ]}
        preserveSelection
      />,
    );
    // Let the effect run; it must NOT reset the deliberate pick.
    await Promise.resolve();
    expect(onValueChange).not.toHaveBeenCalled();
  });

  it("falls back to the first option only when the value disappears", async () => {
    const onValueChange = vi.fn();
    render(
      <BaseEntitySelector
        value="b"
        onValueChange={onValueChange}
        options={[
          { value: "c", label: "C" },
          { value: "d", label: "D" },
        ]}
        preserveSelection
      />,
    );
    await waitFor(() => expect(onValueChange).toHaveBeenCalledWith("c"));
  });

  it("autoSelectFirst WITHOUT preserveSelection leaves a stale invalid value (the bug preserveSelection fixes)", async () => {
    const onValueChange = vi.fn();
    render(
      <BaseEntitySelector
        value="b"
        onValueChange={onValueChange}
        options={[{ value: "c", label: "C" }]}
        autoSelectFirst
      />,
    );
    await Promise.resolve();
    // value "b" is truthy, so `autoSelectFirst && !value` never fires — the
    // stale, now-invalid "b" silently persists. This is exactly why the
    // dependent selectors switched to preserveSelection.
    expect(onValueChange).not.toHaveBeenCalled();
  });

  it("does nothing when neither flag is set", async () => {
    const onValueChange = vi.fn();
    render(
      <BaseEntitySelector
        value={null}
        onValueChange={onValueChange}
        options={OPTS}
      />,
    );
    await Promise.resolve();
    expect(onValueChange).not.toHaveBeenCalled();
  });
});
