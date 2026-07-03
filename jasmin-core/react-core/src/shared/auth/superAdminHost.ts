/// <reference types="vite/client" />

/**
 * Single source of truth for super-admin (platform) host detection.
 *
 * The platform / super-admin app is served from a configurable subdomain
 * (the backend equivalent is ``SUPER_ADMIN_SUBDOMAIN``). The leftmost
 * hostname label decides the auth realm: ``<sub>``, ``<sub>.localhost``,
 * ``<sub>.example.com`` are the platform; a tenant lives under any other
 * subdomain. A non-leftmost match (e.g. ``solawi.<sub>.example.com``) is a
 * tenant, not the platform.
 *
 * Driven by ``VITE_SUPER_ADMIN_SUBDOMAIN`` (default ``"marillen"`` — so
 * behaviour is unchanged when the env var is unset).
 */
const SUPER_ADMIN_SUBDOMAIN: string =
  import.meta.env.VITE_SUPER_ADMIN_SUBDOMAIN || "marillen";

/** True when ``host`` is the super-admin / platform host. Case-insensitive,
 * mirroring the original ``/^marillen(\.|$)/i`` check — hostnames are normally
 * already lowercased, but a differently-cased env var must still match. */
export function isSuperAdminHostname(host: string): boolean {
  const normalizedHost = host.toLowerCase();
  const sub = SUPER_ADMIN_SUBDOMAIN.toLowerCase();
  return normalizedHost === sub || normalizedHost.startsWith(sub + ".");
}
