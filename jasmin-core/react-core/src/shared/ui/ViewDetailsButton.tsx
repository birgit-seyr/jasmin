import { Button } from "antd";
import type { ReactNode } from "react";

export interface ViewDetailsButtonProps {
  onClick: () => void;
  label: ReactNode;
  disabled?: boolean;
}

export const ViewDetailsButton = ({
  onClick,
  label,
  disabled,
}: ViewDetailsButtonProps) => (
  <Button type="primary" size="small" onClick={onClick} disabled={disabled}>
    {label}
  </Button>
);

