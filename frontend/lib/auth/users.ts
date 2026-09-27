/** Demo identity store for the console (server-side only: imported by the
 * sign-in action, never by a client component). Passwords are stored as
 * scrypt hashes with a per-user salt and compared in constant time. The
 * plaintext demo passwords appear only on the sign-in page's "demo
 * accounts" list (lib/auth/demoAccounts.ts), as a demo product would.
 * Production would replace this file with an identity provider (OIDC). */

import { scryptSync, timingSafeEqual } from "node:crypto";
import type { SessionUser } from "./token";

interface StoredUser extends SessionUser {
  salt: string;
  hash: string;
}

const USERS: StoredUser[] = [
  {
    sub: "u-admin", name: "Platform Admin", email: "admin@kaveri-health.example", role: "platform_admin",
    title: "Presenter · full access", actorId: "admin-platform",
    salt: "vfChvUOOdnDS3e1CW45t2A", hash: "NS_-9tHzZc4FazzhRUOnW47PxExu3RSNuHcYfOTW4Zg",
  },
  {
    sub: "u-arjun", name: "Arjun Mehta", email: "arjun.mehta@kaveri-health.example", role: "claims_officer",
    title: "Senior claims officer", actorId: "officer-arjun",
    salt: "d5qNKBvloPciWpRHeTNzAA", hash: "dg7HucOQdMpPHeMZkNprx0QePMfjSC-DEpN2JR5U01w",
  },
  {
    sub: "u-divya", name: "Divya Nair", email: "divya.nair@kaveri-health.example", role: "compliance_officer",
    title: "Compliance & privacy officer", actorId: "compliance-divya",
    salt: "_sWA9P8WUw-b4CKGA-GA1w", hash: "VErLK62DO9Sk9FEJXG4IwEp8CWxa-jmv3k9wrGIYULU",
  },
  {
    sub: "u-priya", name: "Priya Raman", email: "priya.raman@example.com", role: "policyholder",
    title: "Policyholder · KHA-SIL-004512", actorId: "KHA-SIL-004512",
    salt: "qAEoWn0koS8nin3iyD5Chg", hash: "eB0D4oxFGrc0ha1w4gPRm44EfeognlV9fRVp7xB83kk",
  },
];

// Used when the email is unknown, so a wrong email costs the same scrypt
// work as a wrong password (no user-enumeration by timing).
const DUMMY = { salt: "dummy-salt-for-timing-00", hash: scryptSync("dummy", "dummy-salt-for-timing-00", 32).toString("base64url") };

export function verifyCredentials(email: string, password: string): SessionUser | null {
  const user = USERS.find((u) => u.email.toLowerCase() === email.trim().toLowerCase());
  const record = user ?? DUMMY;
  const actual = scryptSync(password, record.salt, 32);
  const expected = Buffer.from(record.hash, "base64url");
  const ok = expected.length === actual.length && timingSafeEqual(expected, actual);
  if (!user || !ok) return null;
  const { salt: _salt, hash: _hash, ...session } = user;
  void _salt;
  void _hash;
  return session;
}
