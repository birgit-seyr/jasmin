/**
 * clearCacheOnSessionEnd: the query cache holds the signed-in user's own data,
 * so it empties when the session ends, and only then. The token store is the
 * real one, as AuthContext and the axios interceptor clear it.
 */
import { QueryClient } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { clearAccessToken, setAccessToken } from "@shared/services/tokenStore";
import { clearCacheOnSessionEnd } from "../clearCacheOnSessionEnd";

let queryClient: QueryClient;
let unsubscribe: () => void;

beforeEach(() => {
  clearAccessToken();
  queryClient = new QueryClient();
  unsubscribe = clearCacheOnSessionEnd(queryClient);
});

afterEach(() => {
  unsubscribe();
  clearAccessToken();
  queryClient.clear();
});

describe("clearCacheOnSessionEnd", () => {
  it("empties the cache when the session ends", () => {
    setAccessToken("first-user-token");
    queryClient.setQueryData(["my_member_data"], { member_number: 7 });

    clearAccessToken();

    expect(queryClient.getQueryData(["my_member_data"])).toBeUndefined();
    expect(queryClient.getQueryCache().getAll()).toHaveLength(0);
  });

  it("keeps the cache while the session goes on under a refreshed token", () => {
    setAccessToken("token-1");
    queryClient.setQueryData(["my_member_data"], { member_number: 7 });

    setAccessToken("token-2");

    expect(queryClient.getQueryData(["my_member_data"])).toEqual({
      member_number: 7,
    });
  });

  it("keeps the cache when the boot refresh finds no session", () => {
    queryClient.setQueryData(["waiting_list_offer"], { id: "o1" });

    clearAccessToken();

    expect(queryClient.getQueryData(["waiting_list_offer"])).toEqual({ id: "o1" });
  });

  it("ends a session that was open before it subscribed", () => {
    unsubscribe();
    setAccessToken("first-user-token");
    unsubscribe = clearCacheOnSessionEnd(queryClient);
    queryClient.setQueryData(["my_member_data"], { member_number: 7 });

    clearAccessToken();

    expect(queryClient.getQueryData(["my_member_data"])).toBeUndefined();
  });
});
