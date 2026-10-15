import { useEffect } from "react";

/**
 * "+" adds a row, as the add button does: not while a field has the focus, so
 * the key still types there, nor with a modifier held, nor while a row or a
 * dialog is open for editing.
 */
export function useAddShortcut(
  enabled: boolean,
  editing: boolean,
  add: () => void,
): void {
  useEffect(() => {
    if (!enabled) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "+") return;
      if (event.ctrlKey || event.metaKey || event.altKey) return;

      const target = event.target as HTMLElement | null;
      if (target) {
        const tag = target.tagName;
        if (
          tag === "INPUT" ||
          tag === "TEXTAREA" ||
          tag === "SELECT" ||
          target.isContentEditable
        ) {
          return;
        }
      }
      if (editing) return;

      event.preventDefault();
      add();
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [enabled, editing, add]);
}
