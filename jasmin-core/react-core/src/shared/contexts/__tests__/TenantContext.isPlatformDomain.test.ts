import { afterEach, describe, expect, it } from "vitest";
import { isPlatformDomain } from "../TenantContext";

/**
 * isPlatformDomain decides whether the current host loads the SuperAdmin
 * shell or a Tenant shell. Wrong answer = wrong app shown to the user;
 * worst case super-admin UI exposed on a tenant subdomain. Lock it.
 */

const ORIGINAL = window.location;

function setHost(hostname: string) {
  // jsdom's location is read-only; redefine for the test.
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { ...ORIGINAL, hostname },
  });
}

afterEach(() => {
  Object.defineProperty(window, "location", {
    configurable: true,
    value: ORIGINAL,
  });
});

describe("isPlatformDomain", () => {
  describe("development hosts (.localhost)", () => {
    it("returns true for marillen.localhost", () => {
      setHost("marillen.localhost");
      expect(isPlatformDomain()).toBe(true);
    });

    it("returns false for any tenant subdomain on localhost", () => {
      setHost("solawi.localhost");
      expect(isPlatformDomain()).toBe(false);
    });

    it("returns false for plain localhost (no subdomain)", () => {
      setHost("localhost");
      expect(isPlatformDomain()).toBe(false);
    });
  });

  describe("production hosts", () => {
    it("returns true when the leftmost label is 'marillen'", () => {
      setHost("marillen.example.com");
      expect(isPlatformDomain()).toBe(true);
    });

    it("returns false for any other tenant subdomain", () => {
      setHost("solawi.example.com");
      expect(isPlatformDomain()).toBe(false);
    });

    it("does not match 'marillen' as a non-leftmost label (defence in depth)", () => {
      // A hostname like solawi.marillen.example.com should be treated as a
      // tenant subdomain, NOT as the platform shell.
      setHost("solawi.marillen.example.com");
      expect(isPlatformDomain()).toBe(false);
    });
  });
});
