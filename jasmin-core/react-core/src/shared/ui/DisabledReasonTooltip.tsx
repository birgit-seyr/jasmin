import { Tooltip } from "antd";
import type { ReactElement } from "react";
import { useId } from "react";

export interface DisabledReasonTooltipProps {
  /** Why the action is unavailable. Empty or null renders the action alone. */
  reason: string | null | undefined;
  /** Renders the action. Receives the id of the reason text for the action's
   *  ``aria-describedby``, or ``undefined`` while there is no reason. */
  children: (reasonId: string | undefined) => ReactElement;
}

/**
 * Explains why an action is unavailable: a light tooltip on hover, and the same
 * text hidden on screen but reachable through ``aria-describedby``, so a
 * keyboard or screen-reader user gets the reason too. The caller still sets
 * ``disabled`` on its own control.
 */
export default function DisabledReasonTooltip({
  reason,
  children,
}: DisabledReasonTooltipProps) {
  const reasonId = useId();

  if (!reason) return children(undefined);

  return (
    <Tooltip
      title={reason}
      trigger="hover"
      classNames={{ root: "custom-tooltip" }}
    >
      {/* A disabled button fires no mouse events, so the span takes the hover. */}
      <span className="disabled-reason-tooltip">
        {children(reasonId)}
        <span id={reasonId} className="sr-only">
          {reason}
        </span>
      </span>
    </Tooltip>
  );
}
