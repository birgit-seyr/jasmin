import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  useMemo,
} from "react";
import type { ReactNode } from "react";
import { useAuth } from "./AuthContext";
import { authPartialUpdate } from "@shared/api/generated/auth/auth";
import type { UserProfileUpdateRequest } from "@shared/api/generated/models";

const EDIT_MODES = {
  INLINE: "inline",
  MODAL: "modal",
} as const;

type EditMode = (typeof EDIT_MODES)[keyof typeof EDIT_MODES];

interface ModalPreferences {
  edit_mode?: EditMode;
}

interface ModalContextValue {
  editMode: EditMode;
  loading: boolean;
  error: string | null;
  saveEditMode: (newMode: EditMode) => Promise<void>;
  savePreferences: (newPreferences: ModalPreferences) => Promise<void>;
  toggleEditMode: () => void;
  isModalMode: boolean;
  isInlineMode: boolean;
  EDIT_MODES: typeof EDIT_MODES;
}

const ModalContext = createContext<ModalContextValue | undefined>(undefined);

export function ModalProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const [editMode, setEditMode] = useState<EditMode>(
    (user?.edit_mode as EditMode) || EDIT_MODES.INLINE,
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Initialize edit mode from user
  useEffect(() => {
    if (user?.edit_mode) {
      setEditMode(user.edit_mode as EditMode);
    }
  }, [user]);

  // Save preferences to backend
  const savePreferences = useCallback(
    async (newPreferences: ModalPreferences) => {
      if (!user) {
        // If no user, just update local state
        if (newPreferences.edit_mode) {
          setEditMode(newPreferences.edit_mode);
        }
        return;
      }

      try {
        setLoading(true);
        setError(null);

        // edit_mode is a client-side preference — the profile PATCH endpoint
        // ignores unknown fields, so we send it through the typed client as a
        // best-effort hint and rely on localStorage below for persistence.
        await authPartialUpdate(
          String(user.id),
          newPreferences as unknown as UserProfileUpdateRequest,
        );

        // Update local state
        if (newPreferences.edit_mode) {
          setEditMode(newPreferences.edit_mode);
        }

        // Update auth data in localStorage
        try {
          const storedAuth = localStorage.getItem("auth");
          if (storedAuth) {
            const auth = JSON.parse(storedAuth);
            if (auth.user) {
              if (newPreferences.edit_mode)
                auth.user.edit_mode = newPreferences.edit_mode;
              localStorage.setItem("auth", JSON.stringify(auth));
            }
          }
        } catch (storageError) {
          console.error("Failed to update stored auth:", storageError);
        }
      } catch (err) {
        console.error("Failed to save edit mode preferences:", err);
        const errorMessage =
          (err as Error).message || "Failed to save edit mode preferences";
        setError(errorMessage);
        throw err;
      } finally {
        setLoading(false);
      }
    },
    [user],
  );

  const saveEditMode = useCallback(
    async (newMode: EditMode) => {
      if (!newMode || newMode === editMode) {
        return;
      }
      await savePreferences({ edit_mode: newMode });
    },
    [editMode, savePreferences],
  );

  const toggleEditMode = useCallback(() => {
    const newMode =
      editMode === EDIT_MODES.INLINE ? EDIT_MODES.MODAL : EDIT_MODES.INLINE;
    saveEditMode(newMode);
  }, [editMode, saveEditMode]);

  // Memoized so consumers of useModal() (e.g. every mounted EditableTable)
  // don't re-render on every ModalProvider render — only when a value here
  // actually changes.
  const value: ModalContextValue = useMemo(
    () => ({
      editMode,
      loading,
      error,
      saveEditMode,
      savePreferences,
      toggleEditMode,
      isModalMode: editMode === EDIT_MODES.MODAL,
      isInlineMode: editMode === EDIT_MODES.INLINE,
      EDIT_MODES,
    }),
    [editMode, loading, error, saveEditMode, savePreferences, toggleEditMode],
  );

  return (
    <ModalContext.Provider value={value}>{children}</ModalContext.Provider>
  );
}

export function useModal() {
  const context = useContext(ModalContext);
  if (!context) {
    throw new Error("useModal must be used within a ModalProvider");
  }
  return context;
}
