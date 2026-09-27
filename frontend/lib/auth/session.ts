/** Reads the signed-in console user in server components and actions. */

import { cookies } from "next/headers";
import { SESSION_COOKIE, type SessionUser, verifySession } from "./token";

export async function getSessionUser(): Promise<SessionUser | null> {
  const payload = verifySession((await cookies()).get(SESSION_COOKIE)?.value);
  if (!payload) return null;
  const { iat: _iat, exp: _exp, ...user } = payload;
  void _iat;
  void _exp;
  return user;
}
