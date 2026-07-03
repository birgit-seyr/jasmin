import { Alert } from "antd";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

/**
 * Browser-level offline banner.
 *
 * Listens to `online`/`offline` events on `window` and shows a sticky red
 * banner along the top while the browser reports the network as down. Sits
 * above the global query/mutation error toasts — when offline we don't
 * want 12 individual toasts from in-flight requests; this banner is the
 * single source of truth.
 */
export default function OfflineBanner() {
  const { t } = useTranslation();
  const [offline, setOffline] = useState<boolean>(
    typeof navigator !== "undefined" && navigator.onLine === false,
  );

  useEffect(() => {
    const handleOnline = () => setOffline(false);
    const handleOffline = () => setOffline(true);
    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, []);

  if (!offline) return null;

  return (
    <Alert
      type="error"
      banner
      showIcon
      message={t("common.offline_banner")}
      style={{ position: "sticky", top: 0, zIndex: 1100 }}
    />
  );
}
