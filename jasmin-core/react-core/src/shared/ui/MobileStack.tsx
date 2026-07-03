import type { FC, ReactNode } from "react";
import { useIsMobile } from "@hooks/index";

interface MobileStackProps {
  children: ReactNode;
}

/**
 * Wraps content in a column-flex stack on mobile, and renders an unstyled
 * `<div>` on desktop. Used for selector toolbars across commissioning pages.
 */
const MobileStack: FC<MobileStackProps> = ({ children }) => {
  const isMobile = useIsMobile();
  return (
    <div
      className={isMobile ? "flex-col gap-8" : undefined}
      style={
        isMobile
          ? {
              marginBottom: "8px",
            }
          : undefined
      }
    >
      {children}
    </div>
  );
};

export default MobileStack;
