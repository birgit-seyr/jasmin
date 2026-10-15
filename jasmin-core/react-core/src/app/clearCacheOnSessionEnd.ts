import type { QueryClient } from "@tanstack/react-query";
import { getAccessToken, subscribeAccessToken } from "@shared/services/tokenStore";

/**
 * Empties `queryClient` whenever a session ends: logout, a refresh the server
 * refused, a failed manual refresh. Every one of them clears the access
 * token. The cache holds the signed-in user's own data (member and customer
 * data, the GDPR export, the SEPA mandate, the 2FA status), which would
 * otherwise still paint, and be exported, for the next user who signs in on
 * the same device. A token cleared while there was none, as when the boot
 * refresh finds no session, ends nothing. Returns the unsubscribe.
 */
export function clearCacheOnSessionEnd(queryClient: QueryClient): () => void {
  let signedIn = getAccessToken() !== null;
  return subscribeAccessToken((token) => {
    if (signedIn && token === null) queryClient.clear();
    signedIn = token !== null;
  });
}
