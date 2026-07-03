/**
 * Seam test for ``CancelSubscriptionModal`` — a destructive financial flow
 * (it routes through the cancel ACTION endpoint that truncates the term,
 * deletes future deliveries and drops PLANNED charges).
 *
 * Boundary mocked: the generated ``commissioningAbosCancelCreate`` API fn,
 * ``notify``, and the two UI seams that are awkward in jsdom — AntD's
 * ``DatePicker`` (stubbed to a plain date input) and ``ModalCancelSaveFooter``
 * (stubbed to a plain primary button). The component's own validation +
 * payload-shaping logic runs for real.
 *
 * Dates are derived from the REAL "today" the same way the component does, so
 * the next-Sunday floor lines up regardless of when the suite runs.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import dayjs from "dayjs";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

// CancelSubscriptionModal reads ``useDateFormat().formatDate`` (which pulls
// the tenant context). Stub it so the test doesn't need a <TenantProvider>;
// spread the real barrel so any other @hooks export stays intact.
vi.mock("@hooks/index", async (importOriginal) => ({
  ...((await importOriginal()) as Record<string, unknown>),
  useDateFormat: () => ({
    dateFormat: "DD.MM.YYYY",
    mobileDateFormat: "DD.MM.",
    formatDate: (v: unknown) =>
      v == null || v === ""
        ? null
        : dayjs(v as dayjs.ConfigType).format("DD.MM.YYYY"),
    formatDateWithFallback: (v: unknown, fb: string = "-") =>
      v == null || v === ""
        ? fb
        : dayjs(v as dayjs.ConfigType).format("DD.MM.YYYY"),
  }),
}));

const cancelCreateMock = vi.fn();
vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  commissioningAbosCancelCreate: (...args: unknown[]) =>
    cancelCreateMock(...args),
}));

const notifySuccessMock = vi.fn();
const notifyErrorMock = vi.fn();
vi.mock("@shared/utils", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@shared/utils")>();
  return {
    ...actual,
    notify: {
      success: (...args: unknown[]) => notifySuccessMock(...args),
      error: (...args: unknown[]) => notifyErrorMock(...args),
    },
  };
});

// Footer → a plain primary button so we can fire the submit without AntD's
// Modal portal/button machinery.
vi.mock("@shared/modals/shared", () => ({
  ModalCancelSaveFooter: ({
    onPrimary,
    onCancel,
  }: {
    onPrimary: () => void;
    onCancel: () => void;
  }) => (
    <div>
      <button data-testid="primary" onClick={onPrimary}>
        primary
      </button>
      <button data-testid="footer-cancel" onClick={onCancel}>
        cancel
      </button>
    </div>
  ),
}));

// DatePicker → a controlled date input. ``onChange`` receives a dayjs value,
// matching what the real picker hands ``setEffectiveAt``.
vi.mock("antd", async (importOriginal) => {
  const actual = await importOriginal<typeof import("antd")>();
  const StubPicker = ({
    value,
    onChange,
  }: {
    value: dayjs.Dayjs | null;
    onChange: (d: dayjs.Dayjs | null) => void;
  }) => (
    <input
      data-testid="effective-at"
      value={value ? value.format("YYYY-MM-DD") : ""}
      onChange={(e) =>
        onChange(e.target.value ? dayjs(e.target.value) : null)
      }
    />
  );
  return { ...actual, DatePicker: StubPicker };
});

import { CancelSubscriptionModal } from "../CancelSubscriptionModal";

// The next Sunday on/after today — a valid effective_at by every rule.
const today = dayjs().startOf("day");
const nextSunday = today.add((7 - today.day()) % 7, "day");

const abo = {
  id: "abo-42",
  member_first_name: "Mara",
  member_last_name: "Beispiel",
  share_type_variation_string: "Gemüse M",
  // Wide window so ``nextSunday`` always sits inside [valid_from, valid_until].
  valid_from: today.subtract(1, "year").format("YYYY-MM-DD"),
  valid_until: nextSunday.add(1, "year").format("YYYY-MM-DD"),
};

function renderModal(overrides: Record<string, unknown> = {}) {
  const onClose = vi.fn();
  const onCancelled = vi.fn();
  render(
    <CancelSubscriptionModal
      isOpen
      onClose={onClose}
      onCancelled={onCancelled}
      abo={abo as never}
      {...overrides}
    />,
  );
  return { onClose, onCancelled };
}

function setDate(value: string) {
  fireEvent.change(screen.getByTestId("effective-at"), {
    target: { value },
  });
}

beforeEach(() => {
  cancelCreateMock.mockReset().mockResolvedValue(undefined);
  notifySuccessMock.mockReset();
  notifyErrorMock.mockReset();
});

describe("CancelSubscriptionModal", () => {
  it("POSTs effective_at + reason to the cancel action and closes on success", async () => {
    const { onClose, onCancelled } = renderModal();

    setDate(nextSunday.format("YYYY-MM-DD"));
    fireEvent.click(screen.getByTestId("primary"));

    await waitFor(() => expect(cancelCreateMock).toHaveBeenCalledTimes(1));
    expect(cancelCreateMock).toHaveBeenCalledWith("abo-42", {
      effective_at: nextSunday.format("YYYY-MM-DD"),
      // No reason typed → omitted (undefined), not an empty string.
      reason: undefined,
    });
    expect(notifySuccessMock).toHaveBeenCalledTimes(1);
    expect(onCancelled).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(notifyErrorMock).not.toHaveBeenCalled();
  });

  it("blocks a non-Sunday date client-side without calling the API", async () => {
    renderModal();

    // The day AFTER next Sunday is a Monday → fails the Sunday rule.
    setDate(nextSunday.add(1, "day").format("YYYY-MM-DD"));
    fireEvent.click(screen.getByTestId("primary"));

    await waitFor(() => expect(notifyErrorMock).toHaveBeenCalledTimes(1));
    expect(notifyErrorMock).toHaveBeenCalledWith(
      "members.cancel_abo_must_be_sunday",
    );
    expect(cancelCreateMock).not.toHaveBeenCalled();
  });

  it("blocks a date after valid_until (would extend the term) without calling the API", async () => {
    // Term ends at the soonest valid Sunday; pick the Sunday after that.
    renderModal({
      abo: {
        ...abo,
        valid_until: nextSunday.format("YYYY-MM-DD"),
      } as never,
    });

    setDate(nextSunday.add(7, "day").format("YYYY-MM-DD"));
    fireEvent.click(screen.getByTestId("primary"));

    await waitFor(() => expect(notifyErrorMock).toHaveBeenCalledTimes(1));
    expect(notifyErrorMock).toHaveBeenCalledWith(
      "members.cancel_abo_effective_after_end",
    );
    expect(cancelCreateMock).not.toHaveBeenCalled();
  });

  it("blocks a date before valid_from (term not begun) without calling the API", async () => {
    // Subscription starts a week after the next-Sunday floor; picking the
    // floor itself is a valid Sunday >= today but before the term begins.
    renderModal({
      abo: {
        ...abo,
        valid_from: nextSunday.add(7, "day").format("YYYY-MM-DD"),
      } as never,
    });

    setDate(nextSunday.format("YYYY-MM-DD"));
    fireEvent.click(screen.getByTestId("primary"));

    await waitFor(() => expect(notifyErrorMock).toHaveBeenCalledTimes(1));
    expect(notifyErrorMock).toHaveBeenCalledWith(
      "members.cancel_abo_effective_before_start",
    );
    expect(cancelCreateMock).not.toHaveBeenCalled();
  });

  it("does nothing when no date is picked (primary button is inert)", () => {
    renderModal();
    fireEvent.click(screen.getByTestId("primary"));
    expect(cancelCreateMock).not.toHaveBeenCalled();
    expect(notifyErrorMock).not.toHaveBeenCalled();
  });

  it("surfaces the API failure via notify.error and keeps the modal open", async () => {
    cancelCreateMock.mockRejectedValueOnce(new Error("server said no"));
    const { onClose, onCancelled } = renderModal();

    setDate(nextSunday.format("YYYY-MM-DD"));
    fireEvent.click(screen.getByTestId("primary"));

    await waitFor(() => expect(notifyErrorMock).toHaveBeenCalledTimes(1));
    expect(notifyErrorMock).toHaveBeenCalledWith("server said no");
    expect(notifySuccessMock).not.toHaveBeenCalled();
    expect(onCancelled).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });
});
