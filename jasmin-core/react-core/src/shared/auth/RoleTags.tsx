import { Tag } from "antd";
import { useMemo } from "react";
import { ROLES } from "./roles";
import { useRoleOptions } from "./useRoleOptions";

// Pastel colour per role for the role tags. Keep contrast readable on white.
// Single source of truth — do not re-declare per page.
const ROLE_TAG_COLORS: Record<
  string,
  { bg: string; border: string; text: string }
> = {
  [ROLES.ADMIN]: { bg: "#ffe0e0", border: "#ffb3b3", text: "#a8071a" },
  [ROLES.MANAGEMENT]: { bg: "#ffe7d1", border: "#ffc999", text: "#ad4e00" },
  [ROLES.OFFICE]: { bg: "#fff5cc", border: "#ffe680", text: "#876800" },
  [ROLES.STAFF]: { bg: "#dff5d4", border: "#b3e3a0", text: "#1f6313" },
  [ROLES.GARDENER]: { bg: "#d4f0e0", border: "#9bd9b8", text: "#0f5132" },
  [ROLES.MEMBER]: { bg: "#dceeff", border: "#a9d1ff", text: "#003a8c" },
  [ROLES.CUSTOMER]: { bg: "#ecdcff", border: "#c9a9ff", text: "#391085" },
};
const DEFAULT_ROLE_COLOR = {
  bg: "var(--color-bg-hover)",
  border: "var(--color-border)",
  text: "#595959",
};

interface RoleTagsProps {
  /** The user's role slugs (e.g. ``["office", "admin"]``). */
  roles: readonly string[] | null | undefined;
  /** Rendered (muted) when the user has no roles. Omit to render nothing. */
  emptyText?: string;
}

/**
 * The single source of truth for rendering a user's roles as coloured tags:
 * localized labels from {@link useRoleOptions} + the shared per-role pastel
 * palette. Used by the users-admin table and the profile modal so both stay
 * in sync — never re-implement the label/colour lookup per page.
 */
export default function RoleTags({ roles, emptyText }: RoleTagsProps) {
  const roleOptions = useRoleOptions();
  const roleLabelMap = useMemo(
    () =>
      Object.fromEntries(roleOptions.map(({ value, label }) => [value, label])),
    [roleOptions],
  );

  const list = roles ?? [];
  if (list.length === 0) {
    return emptyText ? (
      <span className="text-secondary">{emptyText}</span>
    ) : null;
  }

  return (
    <>
      {list.map((role) => {
        const color = ROLE_TAG_COLORS[role] ?? DEFAULT_ROLE_COLOR;
        return (
          <Tag
            key={role}
            style={{
              backgroundColor: color.bg,
              borderColor: color.border,
              color: color.text,
            }}
          >
            {roleLabelMap[role] ?? role}
          </Tag>
        );
      })}
    </>
  );
}
