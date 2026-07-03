import { Layout } from "antd";
import { AppRouter } from "@routing/AppRouter";

const { Content } = Layout;

export default function MainContent() {
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
      <AppRouter />
    </Content>
  );
}
