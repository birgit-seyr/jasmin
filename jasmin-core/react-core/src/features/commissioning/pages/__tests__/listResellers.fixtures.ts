/**
 * The resellers and offer groups the reseller list tests start from, and the
 * builders for a reseller row and the login the backend nests into it.
 */
import type { AdminUserRow, OfferGroup, Reseller } from "@shared/api/generated/models";

type Row = Record<string, unknown>;

export const STANDARD: OfferGroup = { id: "og-standard", number: 1, name: "Standard", is_default: true };
export const WHOLESALE: OfferGroup = { id: "og-wholesale", number: 2, name: "Wholesale" };

/** A reseller's login, as the backend nests it into the reseller row. */
export function login(overrides: Partial<AdminUserRow> & { id: string }): Row {
  const row: AdminUserRow = {
    email: "", first_name: "", last_name: "", roles: ["customer"], user_language: "de",
    account_status: "active", is_active: true, date_joined: "2026-01-12T09:00:00Z",
    last_login: null, activated_at: null, inactivated_at: null, invitation_expires_at: null,
    is_invitation_expired: false, reseller_id: null,
    ...overrides,
  };
  return { ...row };
}

export function reseller(overrides: Partial<Reseller> & { id: string }): Reseller {
  return {
    is_reseller: true, is_active_reseller: true, is_seller: false,
    is_also_delivery_station: false, linked_delivery_station_can_be_deleted: true,
    offer_via_email: false, delivery_note_via_email: false,
    company_name: null, first_name: null, last_name: null, address: "", zip_code: "", city: "",
    email: null, phone: null, note: null, offer_group: STANDARD.id, payment_terms_in_days: 14,
    linked_user_info: null, can_be_deleted: true,
    ...overrides,
  };
}

// Has orders, so the backend protects it; signs in as a customer.
export const HOFLADEN = reseller({
  id: "res-hofladen", company_name: "Hofladen Gruber", first_name: "Anna", last_name: "Gruber",
  address: "Dorfstraße 1", zip_code: "4020", city: "Linz", email: "hofladen@example.com",
  phone: "+43 732 100", note: "Delivery on Mondays",
  is_seller: true, offer_via_email: true, delivery_note_via_email: true, can_be_deleted: false,
  linked_user_info: login({ id: "user-anna", reseller_id: "res-hofladen" }),
});
// Also a delivery station whose pickup days are in use; has no login yet.
export const BIOMARKT = reseller({
  id: "res-biomarkt", company_name: "Biomarkt Sonnenschein", first_name: "Ben",
  last_name: "Huber", address: "Marktplatz 5", zip_code: "4600", city: "Wels",
  email: "einkauf@biomarkt.example", offer_group: WHOLESALE.id,
  is_also_delivery_station: true, linked_delivery_station_can_be_deleted: false,
});
// A delivery station nobody collects from yet; its login is invited.
export const CAFE = reseller({
  id: "res-cafe", company_name: "Café Zentral", address: "Hauptplatz 2", zip_code: "4400",
  city: "Steyr", is_also_delivery_station: true,
  linked_user_info: login({ id: "user-clara", account_status: "pending_invitation" }),
});
// No longer supplied; its login is deactivated.
export const KANTINE = reseller({
  id: "res-kantine", company_name: "Kantine Nord", address: "Industriestraße 9",
  zip_code: "4470", city: "Enns", is_active_reseller: false,
  linked_user_info: login({ id: "user-dora", account_status: "inactive", is_active: false }),
});
