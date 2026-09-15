/**
 * Debounce behaviour of the config-page autosave (``useAutoSave``).
 *
 * Rapid typing must save ~500ms after typing PAUSES, not after the FIRST
 * keystroke. ``markChanged`` can set ``hasChanges``/``delay`` to values they
 * already hold, so React skips the re-render and the arming effect's deps
 * don't change; the ``changeTick`` counter is what resets the timer. A
 * premature save means mid-typing validation errors (each save PATCHes the
 * whole settings object). These tests pin it.
 */
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAutoSave } from "../useAutoSave";

describe("useAutoSave debounce", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("resets the debounce on every keystroke — no save mid-typing", () => {
    const save = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() =>
      useAutoSave({ enabled: true, save, debounceMs: 500 }),
    );

    // Four "keystrokes" 300ms apart. Each gap (300ms) is < the 500ms window,
    // but the whole span (900ms) exceeds it. A correct debounce fires 0 times
    // until typing pauses; a broken one fires once ~500ms after the FIRST key.
    act(() => result.current.markChanged("number"));
    for (let i = 0; i < 3; i++) {
      act(() => vi.advanceTimersByTime(300));
      act(() => result.current.markChanged("number"));
    }
    // A debounce anchored on the FIRST keystroke would already have saved here.
    expect(save).not.toHaveBeenCalled();

    // Typing pauses → exactly one coalesced save.
    act(() => vi.advanceTimersByTime(500));
    expect(save).toHaveBeenCalledTimes(1);
  });

  it("fires a single save one debounce window after the last change", () => {
    const save = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() =>
      useAutoSave({ enabled: true, save, debounceMs: 500 }),
    );

    act(() => result.current.markChanged("number"));
    act(() => vi.advanceTimersByTime(499));
    expect(save).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(1));
    expect(save).toHaveBeenCalledTimes(1);
  });

  it("immediate types (select/checkbox/switch/file) save with no debounce", () => {
    const save = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() =>
      useAutoSave({ enabled: true, save, debounceMs: 500 }),
    );

    act(() => result.current.markChanged("select"));
    act(() => vi.advanceTimersByTime(0));
    expect(save).toHaveBeenCalledTimes(1);
  });

  it("does not arm while disabled", () => {
    const save = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() =>
      useAutoSave({ enabled: false, save, debounceMs: 500 }),
    );

    act(() => result.current.markChanged("number"));
    act(() => vi.advanceTimersByTime(1000));
    expect(save).not.toHaveBeenCalled();
  });
});
