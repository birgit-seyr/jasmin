import { AVAILABLE_ROLES } from "@features/platform/userManagement";

interface RoleChipSelectorProps {
  selectedRoles: string[];
  onToggle: (role: string) => void;
  /** Roles to offer; defaults to the super-admin-assignable {@link AVAILABLE_ROLES}. */
  roles?: string[];
}

/**
 * Clickable role-selector chips shared by the super-admin create-user modal
 * and the tenant-detail inline role editor. Renders one chip per role; the
 * caller owns the surrounding layout wrapper (a ``Flex`` or ``.sa-roles-edit``).
 */
export default function RoleChipSelector({
  selectedRoles,
  onToggle,
  roles = AVAILABLE_ROLES,
}: RoleChipSelectorProps) {
  return (
    <>
      {roles.map((role) => (
        <span
          key={role}
          onClick={() => onToggle(role)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              onToggle(role);
            }
          }}
          role="checkbox"
          aria-checked={selectedRoles.includes(role)}
          tabIndex={0}
          className={`sa-role-chip sa-role-chip--selectable ${
            selectedRoles.includes(role) ? "sa-role-chip--selected" : ""
          }`}
        >
          {role}
        </span>
      ))}
    </>
  );
}
