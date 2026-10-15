import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useAddShortcut } from "../useAddShortcut";

function press(key: string, init: KeyboardEventInit = {}, target: EventTarget = window) {
  const event = new KeyboardEvent("keydown", {
    key,
    bubbles: true,
    cancelable: true,
    ...init,
  });
  target.dispatchEvent(event);
  return event;
}

describe("useAddShortcut", () => {
  it("adds a row on +", () => {
    const add = vi.fn();
    renderHook(() => useAddShortcut(true, false, add));

    const event = press("+");

    expect(add).toHaveBeenCalledTimes(1);
    expect(event.defaultPrevented).toBe(true);
  });

  it("leaves + to the field that has the focus", () => {
    const add = vi.fn();
    renderHook(() => useAddShortcut(true, false, add));
    const input = document.createElement("input");
    document.body.appendChild(input);

    press("+", {}, input);
    input.remove();

    expect(add).not.toHaveBeenCalled();
  });

  it("ignores + with a modifier, while editing, and when switched off", () => {
    const add = vi.fn();
    const { rerender } = renderHook(
      ({ enabled, editing }) => useAddShortcut(enabled, editing, add),
      { initialProps: { enabled: true, editing: false } },
    );

    press("+", { ctrlKey: true });
    rerender({ enabled: true, editing: true });
    press("+");
    rerender({ enabled: false, editing: false });
    press("+");

    expect(add).not.toHaveBeenCalled();
  });
});
