import { Layout } from "antd";
import { useLocation } from "react-router-dom";
import { AppRouter } from "@routing/AppRouter";
import ErrorBoundary from "@shared/ui/ErrorBoundary";

const { Content } = Layout;

export default function MainContent() {
  const location = useLocation();

  return (
    <Content
      // A11Y-27: skip-to-content target. tabIndex={-1} lets the skip link move
      // focus here programmatically without adding a Tab stop.
      id="main-content"
      tabIndex={-1}
      style={{
        padding: "24px",
        background: "var(--color-bg-base)",
        minHeight: "calc(100vh - 64px)",
        flex: 1,
        overflow: "auto",
        width: "100%",
        border: "3px",
        borderLeft: "solid 1px rgb(32, 95, 82)",
      }}
    >
      {/* Per-route safety net: a page render-throw shows the fallback here,
          inside the persistent shell (nav/sidebar/footer survive). resetKeys
          on the route lets a click in the still-alive nav clear the fallback
          without a full reload. */}
      <ErrorBoundary resetKeys={[location.pathname]}>
        <AppRouter />
      </ErrorBoundary>
    </Content>
  );
}
