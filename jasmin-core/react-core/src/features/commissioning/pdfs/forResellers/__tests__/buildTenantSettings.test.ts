/**
 * The reseller documents (offer, delivery note, invoice and their ZUGFeRD
 * XML) take the organic control number from ``buildTenantSettings``, under the
 * office-side gate's rule: a stored number counts only while the farm's
 * organic documentation is on, and without one no line is marked organic, no
 * footer names a control body and the XML carries no organic note.
 */
import { describe, expect, it } from "vitest";
import { buildTenantSettings } from "../pdfBase";

const getSettingFrom =
  (settings: Record<string, unknown>) => (key: string, defaultValue?: unknown) =>
    key in settings ? settings[key] : defaultValue;

const certifiedFarm = { name: "Hof", organic_control_number: " AT-BIO-301 " };

describe("buildTenantSettings organic control number", () => {
  it("carries the stored number, trimmed, by default", () => {
    const settings = buildTenantSettings(certifiedFarm, null, getSettingFrom({}));

    expect(settings.organic_control_number).toBe("AT-BIO-301");
  });

  it("carries it while the organic documentation is on", () => {
    const settings = buildTenantSettings(
      certifiedFarm,
      null,
      getSettingFrom({ uses_organic_documentation: true }),
    );

    expect(settings.organic_control_number).toBe("AT-BIO-301");
  });

  it("drops a stored number while the organic documentation is off", () => {
    const settings = buildTenantSettings(
      certifiedFarm,
      null,
      getSettingFrom({ uses_organic_documentation: false }),
    );

    expect(settings.organic_control_number).toBeNull();
  });

  it("has none for a farm without a number", () => {
    expect(
      buildTenantSettings({ name: "Hof" }, null, getSettingFrom({}))
        .organic_control_number,
    ).toBeNull();
  });
});
