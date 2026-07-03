/**
 * Render-loop smoke test helper.
 *
 * Wraps `children` in a React `<Profiler>` and returns a Vitest mock you can
 * inspect after the test waits for the page to settle. The bound is a LOOSE
 * upper limit — its job is to catch a real setState-in-render loop (which
 * produces thousands of commits), not to pin an exact baseline.
 *
 * Usage:
 *   const profiler = profileRenders();
 *   render(profiler.wrap(<MyPage />));
 *   await screen.findByText("…");
 *   await flushMicrotasks();
 *   expect(profiler.onRender.mock.calls.length).toBeLessThan(80);
 *
 * Healthy baselines observed so far:
 *   - LoginPage      ~6 commits
 *   - MemberDetail   ~5 commits
 *
 * If a page commits more than ~30 times on initial mount, that's worth a
 * second look even if the bound is generous.
 */
import { Profiler, type ReactNode } from "react";
import { vi, type Mock } from "vitest";

export interface ProfileRendersHandle {
  /** The vitest spy — read `.mock.calls.length` after the test waits. */
  onRender: Mock;
  /** Wraps any element in a <Profiler> wired to the spy. */
  wrap: (children: ReactNode, id?: string) => ReactNode;
}

export function profileRenders(): ProfileRendersHandle {
  const onRender = vi.fn();
  return {
    onRender,
    wrap: (children, id = "profiled") => (
      <Profiler id={id} onRender={onRender}>
        {children}
      </Profiler>
    ),
  };
}

/** Flush any trailing microtasks/timers before counting renders. */
export const flushMicrotasks = (ms = 30) =>
  new Promise<void>((resolve) => setTimeout(resolve, ms));
