/** Console session token: `base64url(JSON payload).base64url(HMAC-SHA256)`,
 * kept in an httpOnly cookie. Signed with CONSOLE_SESSION_SECRET (at least
 * 32 characters, from frontend/.env.local); without it every token is
 * rejected, so the console fails closed rather than trusting unsigned data.
 * Used by proxy.ts (Node runtime) and the sign-in server action. */

import { createHmac, timingSafeEqual } from "node:crypto";
import type { Role } from "./roles";

export const SESSION_COOKIE = "cg_session";
export const SESSION_TTL_S = 8 * 60 * 60;

export interface SessionUser {
  sub: string;
  name: string;
  email: string;
  role: Role;
  title: string;
  /** Id recorded on audited human actions (officer decisions, kill switch). */
  actorId: string;
}

export interface SessionPayload extends SessionUser {
  iat: number;
  exp: number;
}

function secret(): Buffer | null {
  const value = process.env.CONSOLE_SESSION_SECRET;
  return value && value.length >= 32 ? Buffer.from(value, "utf8") : null;
}

export function sessionConfigured(): boolean {
  return secret() !== null;
}

function mac(body: string, key: Buffer): string {
  return createHmac("sha256", key).update(body).digest("base64url");
}

export function signSession(user: SessionUser, now = Math.floor(Date.now() / 1000)): string | null {
  const key = secret();
  if (!key) return null;
  const payload: SessionPayload = { ...user, iat: now, exp: now + SESSION_TTL_S };
  const body = Buffer.from(JSON.stringify(payload), "utf8").toString("base64url");
  return `${body}.${mac(body, key)}`;
}

export function verifySession(token: string | undefined | null, now = Math.floor(Date.now() / 1000)): SessionPayload | null {
  const key = secret();
  if (!key || !token) return null;
  const [body, signature, extra] = token.split(".");
  if (!body || !signature || extra !== undefined) return null;
  const expected = Buffer.from(mac(body, key));
  const given = Buffer.from(signature);
  if (expected.length !== given.length || !timingSafeEqual(expected, given)) return null;
  try {
    const payload = JSON.parse(Buffer.from(body, "base64url").toString("utf8")) as SessionPayload;
    return typeof payload.exp === "number" && payload.exp > now ? payload : null;
  } catch {
    return null;
  }
}
