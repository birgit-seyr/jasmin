import { useEffect, useMemo, useRef } from "react";
import { useTranslation } from "react-i18next";
import { matchPath, useLocation } from "react-router-dom";
import { announcePolite } from "@shared/utils/notify";
import { routeGroups } from "./routeConfig";

const BASE_TITLE = "Jasmin";

/**
 * Per-route side effects that make SPA navigation behave like a real page
 * load for keyboard / screen-reader users:
 *
 * 1. Sets the document `<title>` so each page is distinguishable (the static
 *    `index.html` title leaves every SPA route reading "Jasmin", which SR
 *    users rely on and which tab/history/bookmark users need to tell pages
 *    apart). The matched route's `meta.title` is run through `t()` so a title
 *    declared as an i18n key is localized; routes without a `meta.title` fall
 *    back to the bare base title.
 * 2. On each *subsequent* navigation (not the initial mount), moves keyboard
 *    focus into `#main-content` (the tabIndex={-1} skip-link target) and
 *    announces the new page name in the polite live region. Otherwise focus
 *    would stay on the now-stale nav link and the new page would never be
 *    announced — changing `document.title` alone does not trigger an SR
 *    announcement in an SPA.
 *
 * Invisible to sighted mouse users: focus uses `preventScroll` (no scroll
 * jump) and lands on a region with no focus-outline styling, and the
 * announcement writes only to an off-screen live region.
 */
export function useRouteTitle() {
  const { t } = useTranslation();
  const { pathname } = useLocation();
  const isInitialMount = useRef(true);

  // Flatten every group's routes into a single [path, title] list once.
  const routes = useMemo(
    () =>
      routeGroups.flatMap((group) =>
        group.routes.map((route) => ({
          path: route.path,
          title: route.meta?.title,
        })),
      ),
    [],
  );

  useEffect(() => {
    const matched = routes.find(
      (route) => route.title && matchPath(route.path, pathname),
    );
    const pageName = matched?.title ? t(matched.title) : BASE_TITLE;
    document.title = matched?.title ? `${BASE_TITLE} · ${pageName}` : BASE_TITLE;

    // On initial load the browser/SR already announces the page; only manage
    // focus + announce on real navigations.
    if (isInitialMount.current) {
      isInitialMount.current = false;
      return;
    }

    document
      .getElementById("main-content")
      ?.focus({ preventScroll: true });
    announcePolite(pageName);
  }, [pathname, routes, t]);
}
