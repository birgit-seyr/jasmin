import { Navigate } from "react-router-dom";
import { useTenant } from "@hooks/index";
import AmountShareTypeVariations from "@features/commissioning/pages/AmountShareTypeVariations";

export default function Jokers() {
  const { getSetting } = useTenant();
  const usesJokers = getSetting("uses_jokers", true);
  // Direct URL or stale bookmark — bounce off the page when the
  // tenant has disabled jokers. Sidebar entry is hidden in the same
  // condition by ``AboSidebar``.
  if (!usesJokers) {
    return <Navigate to="/abos/dashboard" replace />;
  }
  return <AmountShareTypeVariations jokerMode={true} />;
}
