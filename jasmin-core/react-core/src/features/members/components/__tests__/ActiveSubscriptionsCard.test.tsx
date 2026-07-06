// ActiveSubscriptionsCard buckets a member's subscriptions into active /
// coming / pending (not-yet-confirmed) / past and shows an empty state when
// there are none. These tests lock that bucketing + the empty-state
// (regression of MEM-3).

import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import type { Subscription } from "@shared/api/generated/models";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (k: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : k,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

vi.mock("@hooks/index", () => ({
  useDateFormat: () => ({ formatDate: (d: unknown) => String(d) }),
  useCurrency: () => ({ currencySymbol: "€" }),
}));

vi.mock("@shared/ui", () => ({
  StatusSquare: () => <span data-testid="status-square" />,
  EmptyHint: ({ children }: { children?: React.ReactNode }) => (
    <div>{children}</div>
  ),
}));

vi.mock("../../modals/PastSubscriptionsModal", () => ({ default: () => null }));
vi.mock("../../modals/SubscriptionDetailModal", () => ({ default: () => null }));

import ActiveSubscriptionsCard from "../ActiveSubscriptionsCard";

const sub = (over: Partial<Subscription>): Subscription =>
  ({
    id: "x",
    admin_confirmed: true,
    valid_from: "2020-01-01",
    valid_until: null,
    quantity: 1,
    share_type_name: "Share",
    share_type_variation_size: "M",
    ...over,
  }) as unknown as Subscription;

describe("ActiveSubscriptionsCard", () => {
  it("shows the empty state when the member has no subscriptions", () => {
    render(<ActiveSubscriptionsCard subscriptions={[]} />);
    expect(
      screen.getByText("members.no_active_subscriptions"),
    ).toBeInTheDocument();
  });

  it("buckets active / coming / past correctly", () => {
    render(
      <ActiveSubscriptionsCard
        subscriptions={[
          sub({
            id: "a",
            valid_from: "2020-01-01",
            share_type_name: "HarvestShare",
          }),
          sub({
            id: "c",
            valid_from: "2099-01-01",
            share_type_name: "EggShare",
          }),
          sub({
            id: "p",
            valid_from: "2019-01-01",
            valid_until: "2019-12-31",
            share_type_name: "OldShare",
          }),
        ]}
      />,
    );

    // Active + coming sections render their rows…
    expect(screen.getByText("members.active_subscriptions")).toBeInTheDocument();
    expect(screen.getByText(/HarvestShare/)).toBeInTheDocument();
    expect(screen.getByText("members.coming_subscriptions")).toBeInTheDocument();
    expect(screen.getByText(/EggShare/)).toBeInTheDocument();
    // …and the past one is behind the "show past" button, not inline.
    expect(
      screen.getByText("members.show_past_subscriptions"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/OldShare/)).not.toBeInTheDocument();
    // No empty state when there's content.
    expect(
      screen.queryByText("members.no_active_subscriptions"),
    ).not.toBeInTheDocument();
  });

  it("buckets an unconfirmed, not-yet-past subscription as pending", () => {
    render(
      <ActiveSubscriptionsCard
        subscriptions={[
          sub({
            id: "u",
            admin_confirmed: false,
            valid_from: "2020-01-01",
            share_type_name: "PendingShare",
          }),
        ]}
      />,
    );
    expect(
      screen.getByText("members.pending_subscriptions"),
    ).toBeInTheDocument();
    expect(screen.getByText(/PendingShare/)).toBeInTheDocument();
    expect(
      screen.queryByText("members.no_active_subscriptions"),
    ).not.toBeInTheDocument();
  });

  it("omits a rejected subscription", () => {
    render(
      <ActiveSubscriptionsCard
        subscriptions={[
          sub({
            id: "r",
            admin_confirmed: false,
            admin_rejected_at: "2020-02-01",
            valid_from: "2020-01-01",
            share_type_name: "RejectedShare",
          }),
        ]}
      />,
    );
    expect(screen.queryByText(/RejectedShare/)).not.toBeInTheDocument();
    expect(
      screen.getByText("members.no_active_subscriptions"),
    ).toBeInTheDocument();
  });
});
