/**
 * Debounce behaviour of the config-page autosave (``useAutoSave``).
 *
 * Regression: rapid typing used to trigger a save ~500ms after the FIRST
 * keystroke instead of after typing PAUSED — because ``markChanged`` set
 * ``hasChanges``/``delay`` to values they already held, React skipped the
 * re-render, and the arming effect's deps never changed, so the timer was
 * never reset. That surfaced as "saves too fast / glitches while typing
 * numbers" and mid-typing validation errors (each save PATCHes the whole
 * settings object). The ``changeTick`` counter fixes it; these tests pin it.
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
    // until typing pauses; the OLD bug fired once ~500ms after the FIRST key.
    act(() => result.current.markChanged("number"));
    for (let i = 0; i < 3; i++) {
      act(() => vi.advanceTimersByTime(300));
      act(() => result.current.markChanged("number"));
    }
    // Regression guard: the old code would already have saved here.
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
