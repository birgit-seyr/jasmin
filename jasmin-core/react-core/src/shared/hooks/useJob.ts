import { useNotificationsJobsRetrieve } from "@shared/api/generated/notifications/notifications";

// Re-export the generated model so existing ``import { BackgroundJob } from
// "@hooks"`` consumers keep working off the single source of truth.
export type { BackgroundJob } from "@shared/api/generated/models";

const REFETCH_INTERVAL_MS = 1500;

/**
 * Poll a Huey-backed BackgroundJob until it reaches a terminal state
 * (``done`` or ``failed``). Returns the latest snapshot.
 *
 * Pass ``null`` for ``jobId`` when there's no active job — the query is
 * disabled and fires nothing. Once an id is supplied, polling runs every
 * 1.5 s and stops automatically when the job lands on a terminal status, so a
 * still-open drawer doesn't keep hitting the API.
 *
 * Built on the generated ``useNotificationsJobsRetrieve`` (typed model +
 * shared query key) — the only thing layered on top is the terminal-aware
 * ``refetchInterval``.
 */
export function useJob(jobId: string | null) {
  return useNotificationsJobsRetrieve(jobId ?? "", {
    query: {
      enabled: !!jobId,
      refetchInterval: (query) => {
        const status = query.state.data?.status;
        if (status === "done" || status === "failed") return false;
        return REFETCH_INTERVAL_MS;
      },
    },
  });
}
