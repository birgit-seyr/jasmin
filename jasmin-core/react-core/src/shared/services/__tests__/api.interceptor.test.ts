/**
 * Tier-4 runtime test for the silent-refresh response interceptor in
 * ``services/api.ts`` — the security-critical bit that the rest of the suite
 * only ever mocks away (see TEST-6). Covers:
 *
 *   1. a 401 on a normal endpoint refreshes ONCE and retries the original;
 *   2. concurrent 401s share a single ``/auth/refresh/`` (single-flight);
 *   3. /auth/login|register|logout/ are excluded from the refresh chain;
 *   4. a failed refresh clears the access token.
 *
 * Boundary mocked: the network (MSW) + ``./stepUp`` (step-up isn't exercised
 * here, and stubbing it keeps this test off the i18n/modal import graph). The
 * in-memory tokenStore is kept REAL — the interceptor's whole contract is how
 * it reads/writes that token.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";

import { server } from "@/test/msw/server";

// Step-up is a different branch (403). Stub it so importing api.ts doesn't pull
// in the modal/i18n graph, and so nothing here can accidentally trigger it.
vi.mock("../stepUp", () => ({
  runStepUpFlow: vi.fn(() =>
    Promise.reject(new Error("step-up not exercised in these tests")),
  ),
}));

import axiosInstance from "../api";
import { clearAccessToken, getAccessToken, setAccessToken } from "../tokenStore";

beforeEach(() => {
  clearAccessToken();
});
afterEach(() => {
  clearAccessToken();
});

describe("api.ts silent-refresh interceptor", () => {
  it("refreshes once on a 401 and retries the original request with the new token", async () => {
    let refreshCalls = 0;
    let protectedCalls = 0;
    server.use(
      http.get("/api/protected/", ({ request }) => {
        protectedCalls += 1;
        if (request.headers.get("Authorization") === "Bearer new-token") {
          return HttpResponse.json({ ok: true });
        }
        return HttpResponse.json({ detail: "expired" }, { status: 401 });
      }),
      http.post("/api/auth/refresh/", () => {
        refreshCalls += 1;
        return HttpResponse.json({ access: "new-token" });
      }),
    );
    setAccessToken("stale-token");

    const res = await axiosInstance.get("/api/protected/");

    expect(res.data).toEqual({ ok: true });
    expect(refreshCalls).toBe(1); // exactly one refresh
    expect(protectedCalls).toBe(2); // initial 401 + the retry
    expect(getAccessToken()).toBe("new-token"); // token store updated
  });

  it("dedupes concurrent 401s into a single refresh (single-flight)", async () => {
    let refreshCalls = 0;
    const gated = (path: string) =>
      http.get(path, ({ request }) =>
        request.headers.get("Authorization") === "Bearer fresh-token"
          ? HttpResponse.json({ ok: true })
          : HttpResponse.json({ detail: "expired" }, { status: 401 }),
      );
    server.use(
      gated("/api/a/"),
      gated("/api/b/"),
      http.post("/api/auth/refresh/", async () => {
        refreshCalls += 1;
        // Hold the refresh open so both 401s are guaranteed in-flight.
        await new Promise((r) => setTimeout(r, 20));
        return HttpResponse.json({ access: "fresh-token" });
      }),
    );
    setAccessToken("stale-token");

    const [ra, rb] = await Promise.all([
      axiosInstance.get("/api/a/"),
      axiosInstance.get("/api/b/"),
    ]);

    expect(ra.data).toEqual({ ok: true });
    expect(rb.data).toEqual({ ok: true });
    expect(refreshCalls).toBe(1); // both shared ONE refresh
  });

  it.each(["login", "register", "logout"])(
    "does NOT silent-refresh on a 401 from /auth/%s/",
    async (endpoint) => {
      let refreshCalls = 0;
      server.use(
        http.post(`/api/auth/${endpoint}/`, () =>
          HttpResponse.json({ detail: "denied" }, { status: 401 }),
        ),
        http.post("/api/auth/refresh/", () => {
          refreshCalls += 1;
          return HttpResponse.json({ access: "should-not-happen" });
        }),
      );
      setAccessToken("whatever");

      await expect(
        axiosInstance.post(`/api/auth/${endpoint}/`, {}),
      ).rejects.toMatchObject({ response: { status: 401 } });
      expect(refreshCalls).toBe(0); // the auth endpoints bypass refresh
    },
  );

  it("clears the access token when the refresh itself fails", async () => {
    server.use(
      http.get("/api/protected/", () =>
        HttpResponse.json({ detail: "expired" }, { status: 401 }),
      ),
      http.post("/api/auth/refresh/", () =>
        HttpResponse.json({ detail: "no session" }, { status: 401 }),
      ),
    );
    setAccessToken("stale-token");

    await expect(axiosInstance.get("/api/protected/")).rejects.toBeDefined();
    expect(getAccessToken()).toBeFalsy(); // logged out: token cleared
  });
});
