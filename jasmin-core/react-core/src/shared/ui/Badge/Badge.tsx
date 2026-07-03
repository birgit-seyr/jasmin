import type { ReactNode } from "react";
import styles from "./Badge.module.css";

interface BadgeCountProps {
  count?: number;
  variant?: "error" | "warning" | "success" | "info";
  size?: "small" | "medium" | "large";
  className?: string;
  dot?: boolean;
  children?: ReactNode;
  [key: string]: unknown;
}

const BadgeCount = ({
  count = 0,
  variant = "error",
  size = "medium",
  className = "",
  dot = false,
  children,
  ...props
}: BadgeCountProps) => {
  if (!count || count === 0) {
    return children || null;
  }

  const displayCount = count;

  const badgeClasses = [styles.badge, styles[variant], styles[size], className]
    .filter(Boolean)
    .join(" ");

  const badgeElement = (
    <span className={badgeClasses} {...props}>
      {dot ? "" : displayCount}
    </span>
  );

  if (children) {
    return (
      <div className={styles.wrapper}>
        {children}
        {badgeElement}
      </div>
    );
  }

  return badgeElement;
};

export default BadgeCount;
