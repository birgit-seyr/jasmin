import { AxiosError, AxiosHeaders } from "axios";
import type { TFunction } from "i18next";
import { describe, expect, it, vi } from "vitest";

vi.mock("@shared/i18n", () => ({
  default: {
    t: (key: string) =>
      key === "errors.waiting_list_offer.entry_closed"
        ? "No spot can be offered to this entry."
        : key,
  },
}));

import { offerErrorMessage } from "../offerErrorMessage";

const t = ((key: string) => key) as unknown as TFunction;

function refusal(code: string, message = "Refused."): AxiosError {
  const err = new AxiosError("Request failed", "ERR_BAD_REQUEST", undefined, null, {
    data: { code, message },
    status: 409,
    statusText: "Conflict",
    headers: {},
    config: { headers: new AxiosHeaders() } as never,
  });
  (err as unknown as { isAxiosError: boolean }).isAxiosError = true;
  return err;
}

describe("offerErrorMessage", () => {
  it("names the capacity gate that filled up", () => {
    expect(
      offerErrorMessage(refusal("share_type_variation.over_capacity"), t),
    ).toBe("abos.offer_variation_full");
    expect(
      offerErrorMessage(refusal("delivery_station.over_capacity"), t),
    ).toBe("abos.offer_station_full");
  });

  it("shows why a closed entry can't be offered a spot", () => {
    expect(
      offerErrorMessage(refusal("waiting_list_offer.entry_closed"), t),
    ).toBe("No spot can be offered to this entry.");
  });

  it("shows the server's message for a refusal without a translation", () => {
    expect(
      offerErrorMessage(
        refusal("waiting_list_offer.member_has_no_email", "No address."),
        t,
      ),
    ).toBe("No address.");
  });

  it("falls back to the generic message when the request gave no reason", () => {
    const err = new AxiosError("Network Error", "ERR_NETWORK");
    (err as unknown as { isAxiosError: boolean }).isAxiosError = true;

    expect(offerErrorMessage(err, t)).toBe("abos.offer_failed");
  });
});
