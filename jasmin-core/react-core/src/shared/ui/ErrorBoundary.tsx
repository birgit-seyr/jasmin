import { Component, type ErrorInfo, type ReactNode } from "react";
import { Button, Card, Result, Typography } from "antd";
import {
  isDynamicImportError,
  reloadOnceForChunkError,
} from "@shared/utils/chunkReload";

const { Paragraph } = Typography;

interface Props {
  children: ReactNode;
  /** Optional label rendered in the fallback UI (e.g. "Super admin"). */
  context?: string;
}

interface State {
  error: Error | null;
}

/**
 * Top-level safety net. React 18 unmounts the entire tree if a render throws
 * and there is no boundary; this surfaces as a blank white page with no
 * console error visible to the user.
 *
 * We catch here, log, and offer the user a way out (reload, go to login).
 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // A failed lazy/dynamic import (a stale chunk after a prod deploy, or a Vite
    // dev-server re-optimization in the dev Docker stack) is not an app bug —
    // reload once to pick up the current module URLs instead of dead-ending on
    // the error card. If the loop-guard blocks the reload (the chunk is
    // genuinely broken), fall through and show the recovery UI.
    if (isDynamicImportError(error) && reloadOnceForChunkError()) {
      return;
    }
    console.error("[ErrorBoundary] Uncaught render error:", error, info);
  }

  private handleReload = () => {
    window.location.reload();
  };

  private handleSignIn = () => {
    window.location.href = "/login";
  };

  render() {
    if (!this.state.error) return this.props.children;

    return (
      <div
        style={{
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "var(--color-page-bg)",
          padding: 16,
        }}
      >
        <Card style={{ maxWidth: 560, width: "100%" }}>
          <Result
            status="warning"
            title="Something went wrong"
            subTitle={
              this.props.context
                ? `An error occurred in the ${this.props.context} app.`
                : "An unexpected error occurred."
            }
            extra={[
              <Button type="primary" key="reload" onClick={this.handleReload}>
                Reload page
              </Button>,
              <Button key="login" onClick={this.handleSignIn}>
                Sign in again
              </Button>,
            ]}
          />
          {import.meta.env.DEV && (
            // Raw error messages can leak internals (API URLs, ids,
            // library details) — dev-only. Production users get the
            // generic subtitle; the full error is in the console and
            // the error tracker either way.
            <Paragraph
              type="secondary"
              style={{ marginTop: 16, fontSize: 12, wordBreak: "break-word" }}
            >
              <strong>Details:</strong> {this.state.error.message}
            </Paragraph>
          )}
        </Card>
      </div>
    );
  }
}
