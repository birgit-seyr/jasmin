import { message } from "antd";
import { createElement } from "react";
import i18n from "@shared/i18n";

const DURATION = 4; // seconds

let validationErrorCounter = 0;

// --- Screen-reader live-region announcer ------------------------------------
// AntD's static `message.*` API (5.x) renders its notices in a plain <div>
// with no role / aria-live, so toast feedback is silent to assistive tech.
// To fix the whole channel at once, `<LiveAnnouncer />` (mounted at the app
// root) registers two visually-hidden regions here, and every notify.* call
// mirrors its text into the matching one. The visual toast is unchanged.

type Politeness = "polite" | "assertive";

let announceFn: ((message: string, politeness: Politeness) => void) | null =
  null;

/** Wire the root-mounted live regions. Called once by `<LiveAnnouncer />`. */
export const registerAnnouncer = (
  fn: ((message: string, politeness: Politeness) => void) | null,
) => {
  announceFn = fn;
};

const announce = (content: string, politeness: Politeness) => {
  announceFn?.(content, politeness);
};

/**
 * Announce a message in the polite live region WITHOUT rendering a toast.
 * Used for SPA route changes so screen-reader users hear the new page name
 * after navigation (a bare `document.title` update does not trigger an SR
 * announcement in a single-page app).
 */
export const announcePolite = (content: string) => announce(content, "polite");

const notify = {
  success: (content: string, key?: string) => {
    message.success({ content, duration: DURATION, key });
    announce(content, "polite");
  },
  error: (content: string, key?: string) => {
    message.error({ content, duration: DURATION, key });
    announce(content, "assertive");
  },
  warning: (content: string, key?: string) => {
    message.warning({ content, duration: DURATION, key });
    announce(content, "polite");
  },
  info: (content: string, key?: string) => {
    message.info({ content, duration: DURATION, key });
    announce(content, "polite");
  },
  loading: (content: string, key?: string) => {
    message.loading({ content, duration: 0, key });
    announce(content, "polite");
  },
  validationError: (content: string) => {
    announce(content, "assertive");
    const key = `validation-error-${++validationErrorCounter}`;
    message.open({
      key,
      type: "error",
      content: createElement(
        "span",
        { role: "alert", className: "validation-error-content" },
        content,
        createElement(
          "button",
          {
            type: "button",
            "aria-label": i18n.t("common.close"),
            onClick: () => message.destroy(key),
            className: "validation-error-dismiss",
          },
          createElement("span", { "aria-hidden": true }, "\u00D7"),
        ),
      ),
      duration: 6,
      className: "custom-error-message",
      style: { marginTop: "25vh" },
    });
  },
};

export default notify;
