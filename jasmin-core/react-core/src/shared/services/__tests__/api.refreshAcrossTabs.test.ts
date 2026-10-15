/**
 * Silent refreshes across the tabs of one origin. The tabs share the refresh
 * cookie, and the backend blacklists a refresh token the moment it rotates it:
 * two tabs refreshing at once would send the same cookie, the slower one would
 * lose its session, and its failure would drop the user metadata every tab
 * shares.
 *
 * A "tab" is a fresh copy of api.ts with its own in-memory tokenStore
 * (`vi.resetModules`). The tabs share what the tabs of one browser share:
 * localStorage, `navigator.locks`, and the cookie, which `fakeRefreshBackend`
 * keeps. jsdom has no Web Locks, so the tests that need them install an
 * exclusive lock manager of their own.
 */
import axios from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";
import { delay, http, HttpResponse } from "msw";

import { server } from "@/test/msw/server";

vi.mock("../stepUp", () => ({
  runStepUpFlow: vi.fn(() =>
    Promise.reject(new Error("step-up not exercised in these tests")),
  ),
}));
// The error helpers read messages through i18n; these tests only need codes
// and statuses, and every tab would otherwise initialise i18next again.
vi.mock("@shared/i18n", () => ({ default: { t: (key: string) => key } }));

const storedMetadata = { user: { id: "u-1", roles: ["office"] } };

/** Loads api.ts afresh, as a newly opened tab does. */
async function openTab() {
  vi.resetModules();
  const api = await import("../api");
  const tokens = await import("../tokenStore");
  return {
    refresh: api.performRefresh,
    accessToken: tokens.getAccessToken,
    // As AuthContext's logout sends it.
    logout: () =>
      api.inRefreshTurn(() => api.default.post("/api/auth/logout/", {})),
  };
}

/**
 * The refresh and logout endpoints plus the browser's cookie jar. A POST
 * carries the cookie the jar holds when it goes out. A refresh blacklists that
 * cookie at once and answers `answerAfterMs` later; only then does the new
 * cookie land in the jar. A logout blacklists the cookie and empties the jar.
 * Returns the log of what happened, in order.
 */
function fakeRefreshBackend({ answerAfterMs = 50 } = {}) {
  const events: string[] = [];
  const blacklisted = new Set<number>();
  let jar = 1;
  let minted = 1;
  server.use(
    http.post("/api/auth/refresh/", async () => {
      const sent = jar;
      if (sent === 0) {
        events.push("refused a refresh without a cookie");
        return HttpResponse.json(
          { code: "auth.invalid_token", message: "No refresh cookie" },
          { status: 401 },
        );
      }
      events.push(`sent cookie ${sent}`);
      if (blacklisted.has(sent)) {
        events.push(`refused cookie ${sent}`);
        return HttpResponse.json(
          { code: "auth.invalid_token", message: "Token is blacklisted" },
          { status: 401 },
        );
      }
      blacklisted.add(sent);
      minted += 1;
      const rotated = minted;
      await delay(answerAfterMs);
      jar = rotated;
      events.push(`set cookie ${rotated}`);
      return HttpResponse.json({ access: `access ${rotated}` });
    }),
    http.post("/api/auth/logout/", () => {
      events.push(`logged out cookie ${jar}`);
      blacklisted.add(jar);
      jar = 0;
      return HttpResponse.json({});
    }),
  );
  return events;
}

/** An exclusive `navigator.locks`, granted in the order the tabs ask. */
function installWebLocks() {
  const requested: string[] = [];
  let queue: Promise<unknown> = Promise.resolve();
  Object.defineProperty(navigator, "locks", {
    configurable: true,
    value: {
      request(name: string, callback: (lock: { name: string }) => unknown) {
        requested.push(name);
        const turn = queue.then(() => callback({ name }));
        queue = turn.catch(() => undefined);
        return turn;
      },
    },
  });
  return requested;
}

afterEach(() => {
  Reflect.deleteProperty(navigator, "locks");
});

describe("two tabs refreshing at once", () => {
  it("take turns under the Web Lock: the second sends only after the first resolved, with the cookie it got back", async () => {
    const requestedLocks = installWebLocks();
    const events = fakeRefreshBackend();
    const first = await openTab();
    const second = await openTab();

    const [firstSession, secondSession] = await Promise.all([
      first.refresh().then((session) => {
        events.push("first tab refreshed");
        return session;
      }),
      second.refresh(),
    ]);

    expect(events).toEqual([
      "sent cookie 1",
      "set cookie 2",
      "first tab refreshed",
      "sent cookie 2",
      "set cookie 3",
    ]);
    expect(requestedLocks).toEqual([
      "jasmin-auth-refresh",
      "jasmin-auth-refresh",
    ]);
    expect(firstSession.access).toBe("access 2");
    expect(secondSession.access).toBe("access 3");
    expect(first.accessToken()).toBe("access 2");
    expect(second.accessToken()).toBe("access 3");
  });

  it("don't wait for each other without Web Locks, as in browsers that lack them", async () => {
    const events = fakeRefreshBackend();
    const first = await openTab();
    const second = await openTab();

    const sessions = await Promise.all([first.refresh(), second.refresh()]);

    // Both send the same cookie. The second is refused, gives the first
    // tab's answer time to set the new cookie, and tries again with it.
    expect(events).toEqual([
      "sent cookie 1",
      "sent cookie 1",
      "refused cookie 1",
      "set cookie 2",
      "sent cookie 2",
      "set cookie 3",
    ]);
    expect(sessions.map((session) => session.access)).toEqual([
      "access 2",
      "access 3",
    ]);
  });
});

describe("a logout while another tab refreshes", () => {
  it("waits its turn under the Web Lock and logs out the cookie the refresh got back", async () => {
    installWebLocks();
    const events = fakeRefreshBackend();
    const refreshing = await openTab();
    const leaving = await openTab();

    await Promise.all([refreshing.refresh(), leaving.logout()]);

    // Without the turn the logout would go out first, with cookie 1, and the
    // refresh answering after it would leave cookie 2 alive.
    expect(events).toEqual([
      "sent cookie 1",
      "set cookie 2",
      "logged out cookie 2",
    ]);
    const later = await openTab();
    await expect(later.refresh()).rejects.toBeTruthy();
    expect(events.at(-1)).toBe("refused a refresh without a cookie");
  });
});

describe("a tab whose cookie another tab rotated first", () => {
  it("tries again with the new cookie, keeps its session and the shared metadata", async () => {
    installWebLocks();
    localStorage.setItem("auth", JSON.stringify(storedMetadata));
    // A slow answer, so this tab's POST surely goes out before it lands.
    const events = fakeRefreshBackend({ answerAfterMs: 300 });
    const tab = await openTab();

    // A tab still on an older bundle refreshes without asking for the lock.
    const olderBundle = axios.post("/api/auth/refresh/", {});
    await vi.waitFor(() => expect(events).toContain("sent cookie 1"), {
      interval: 5,
    });
    const session = await tab.refresh();
    await olderBundle;

    expect(events).toEqual([
      "sent cookie 1",
      "sent cookie 1",
      "refused cookie 1",
      "set cookie 2",
      "sent cookie 2",
      "set cookie 3",
    ]);
    expect(session.access).toBe("access 3");
    expect(tab.accessToken()).toBe("access 3");
    expect(JSON.parse(localStorage.getItem("auth") ?? "null")).toEqual(
      storedMetadata,
    );
  });

  it("is logged out everywhere when the cookie is refused again: the shared metadata goes", async () => {
    installWebLocks();
    localStorage.setItem("auth", JSON.stringify(storedMetadata));
    let posts = 0;
    server.use(
      http.post("/api/auth/refresh/", () => {
        posts += 1;
        return HttpResponse.json(
          { code: "auth.invalid_token", message: "Token is blacklisted" },
          { status: 401 },
        );
      }),
    );
    const tab = await openTab();

    await expect(tab.refresh()).rejects.toMatchObject({
      response: { status: 401 },
    });

    expect(posts).toBe(2); // the first try and one more
    expect(tab.accessToken()).toBeNull();
    expect(localStorage.getItem("auth")).toBeNull();
  });
});

describe("a refresh that fails for another reason", () => {
  it("isn't tried again without a cookie, so a signed-out visitor gets the login form at once", async () => {
    let posts = 0;
    server.use(
      http.post("/api/auth/refresh/", () => {
        posts += 1;
        return HttpResponse.json(
          { code: "auth.refresh_missing", message: "Refresh token is required" },
          { status: 401 },
        );
      }),
    );
    const tab = await openTab();

    await expect(tab.refresh()).rejects.toMatchObject({
      response: { status: 401 },
    });

    expect(posts).toBe(1);
  });

  it.each([
    ["gets no answer", () => HttpResponse.error()],
    [
      "meets a server error",
      () => HttpResponse.json({ detail: "Bad gateway" }, { status: 502 }),
    ],
  ])(
    "logs this tab out but keeps the shared metadata when it %s",
    async (_case, answer) => {
      localStorage.setItem("auth", JSON.stringify(storedMetadata));
      server.use(http.post("/api/auth/refresh/", answer));
      const tab = await openTab();

      await expect(tab.refresh()).rejects.toBeDefined();

      expect(tab.accessToken()).toBeNull();
      expect(JSON.parse(localStorage.getItem("auth") ?? "null")).toEqual(
        storedMetadata,
      );
    },
  );
});
