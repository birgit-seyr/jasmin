import { useEffect, useRef, useState } from "react";
import { registerAnnouncer } from "@shared/utils/notify";

/**
 * App-owned screen-reader live regions for the toast feedback channel.
 *
 * AntD's static `message.*` API renders its notices without any
 * `role`/`aria-live`, so success/error/info toasts are invisible to
 * assistive tech. This component mounts a visually-hidden polite +
 * assertive pair once at the app root and registers a writer with
 * `notify.ts`; every `notify.*` call mirrors its text into the matching
 * region. The text is cleared on the next tick before being set so that
 * two identical consecutive messages still re-announce.
 */
export default function LiveAnnouncer() {
  const [politeMessage, setPoliteMessage] = useState("");
  const [assertiveMessage, setAssertiveMessage] = useState("");
  const clearTimers = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => {
    const timers = clearTimers.current;
    registerAnnouncer((message, politeness) => {
      const setter =
        politeness === "assertive" ? setAssertiveMessage : setPoliteMessage;
      // Clear first so re-announcing the same string is observed as a change.
      setter("");
      const timer = setTimeout(() => setter(message), 50);
      timers.push(timer);
    });

    return () => {
      registerAnnouncer(null);
      timers.forEach(clearTimeout);
      timers.length = 0;
    };
  }, []);

  return (
    <>
      <div className="sr-only" role="status" aria-live="polite" aria-atomic="true">
        {politeMessage}
      </div>
      <div
        className="sr-only"
        role="alert"
        aria-live="assertive"
        aria-atomic="true"
      >
        {assertiveMessage}
      </div>
    </>
  );
}
