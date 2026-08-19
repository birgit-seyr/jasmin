import { describe, expect, it } from "vitest";

import {
  TENANT_FILE_FIELDS,
  tenantToSaveablePayload,
  withoutTenantFileFields,
} from "../tenantSettingsMapping";

/**
 * Regression guard for a real production failure: saving ANY scalar on the
 * configuration pages (a checkbox, a phone number) returned
 *
 *   400 {"code": "validation_error", "field": "app_icon",
 *        "message": "Die übermittelten Daten stellen keine Datei dar…"}
 *
 * because the autosave echoes the fetched tenant back as a JSON PATCH, and a
 * ``FileField`` serializes to a URL STRING that DRF's ImageField refuses on
 * write. The field list had been duplicated across three places and only one
 * of them knew about each new file column.
 *
 * These tests exist so a future file column fails here rather than in a user's
 * face on an unrelated form.
 */
describe("tenant file fields are never sent in a JSON PATCH", () => {
  const tenantFromApi = {
    id: "abc123",
    name: "Test Tenant",
    tenant_language: "de",
    allow_upload_for_data_lists: true,
    logo: "http://test.localhost:3000/media/test/logos/logo.png?st=sig",
    bio_logo: "http://test.localhost:3000/media/test/bio_logos/bio.png?st=sig",
    app_icon:
      "http://test.localhost:3000/media/test/app_icons/app_icon.png?st=sig",
    app_icon_version: "1786917683738717",
  };

  it("strips every declared file field", () => {
    const payload = withoutTenantFileFields(tenantFromApi);

    for (const field of TENANT_FILE_FIELDS) {
      expect(payload, `${field} must not be sent`).not.toHaveProperty(field);
    }
  });

  it("keeps the editable scalars", () => {
    const payload = withoutTenantFileFields(tenantFromApi);

    expect(payload.name).toBe("Test Tenant");
    expect(payload.tenant_language).toBe("de");
    expect(payload.allow_upload_for_data_lists).toBe(true);
  });

  it("covers app_icon specifically — the field that broke production", () => {
    expect(TENANT_FILE_FIELDS).toContain("app_icon");
    expect(withoutTenantFileFields(tenantFromApi)).not.toHaveProperty(
      "app_icon",
    );
  });

  it("drops file fields and the read-only icon stamp from the saveable payload", () => {
    // The other save path builds its body through this helper instead.
    const payload = tenantToSaveablePayload(tenantFromApi);

    for (const field of TENANT_FILE_FIELDS) {
      expect(payload).not.toHaveProperty(field);
    }
    // Read-only on the backend: harmless but pointless to echo back.
    expect(payload).not.toHaveProperty("app_icon_version");
    expect(payload.name).toBe("Test Tenant");
  });

  it("leaves a tenant without uploads untouched", () => {
    expect(withoutTenantFileFields({ name: "No Uploads" })).toEqual({
      name: "No Uploads",
    });
  });
});
