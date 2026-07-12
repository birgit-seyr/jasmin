import FitbitIcon from "@mui/icons-material/Fitbit";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import SidebarShell from "./SidebarShell";

interface StaffSidebarProps {
  openKeys?: string[];
  onOpenChange?: (keys: string[]) => void;
}

export default function StaffSidebar({
  openKeys,
  onOpenChange,
}: StaffSidebarProps) {
  const { t } = useTranslation();

  const items = [
    {
      key: "staff-weekly-plan",
      icon: <FitbitIcon />,
      label: (
        <Link to="/staff/weekly-staff-plan">
          {t("staff.weekly_staff_plan")}
        </Link>
      ),
      permission: "staff.team.view",
    },
    {
      key: "staff-saturday-shifts",
      icon: <FitbitIcon />,
      label: (
        <Link to="/staff/saturday-shifts">{t("staff.saturday_shifts")}</Link>
      ),
      permission: "staff.team.view",
    },
    {
      key: "staff-employees",
      icon: <FitbitIcon />,
      label: <Link to="/staff/employees">{t("staff.employees")}</Link>,
      permission: "staff.team.view",
    },
    {
      key: "staff-weekly-plan-categories",
      icon: <FitbitIcon />,
      label: (
        <Link to="/staff/weekly-plan-categories">
          {t("staff.weekly_plan_categories")}
        </Link>
      ),
      permission: "staff.team.view",
    },
    {
      key: "staff-absence-categories",
      icon: <FitbitIcon />,
      label: (
        <Link to="/staff/absence-categories">
          {t("staff.absence_categories")}
        </Link>
      ),
      permission: "staff.team.view",
    },
  ];

  return (
    <SidebarShell
      header={t("nav.staff")}
      items={items}
      openKeys={openKeys}
      onOpenChange={onOpenChange}
    />
  );
}
