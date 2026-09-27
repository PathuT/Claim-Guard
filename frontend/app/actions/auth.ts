"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { HOME_FOR_ROLE, canAccess } from "@/lib/auth/roles";
import { SESSION_COOKIE, SESSION_TTL_S, sessionConfigured, signSession } from "@/lib/auth/token";
import { verifyCredentials } from "@/lib/auth/users";

export interface LoginState {
  error?: string;
  email?: string;
}

/** Only same-site paths, never "//host" or a full URL (no open redirect). */
function safeNext(value: FormDataEntryValue | null): string | null {
  const next = typeof value === "string" ? value : "";
  return next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/login") ? next : null;
}

export async function login(_state: LoginState | undefined, formData: FormData): Promise<LoginState> {
  const email = String(formData.get("email") ?? "").trim();
  const password = String(formData.get("password") ?? "");
  if (!email || !password) return { error: "Enter your email and password.", email };
  if (!sessionConfigured()) {
    return { error: "Sign-in is not configured: set CONSOLE_SESSION_SECRET (32+ characters) in frontend/.env.local and restart.", email };
  }

  const user = verifyCredentials(email, password);
  if (!user) return { error: "Incorrect email or password.", email };

  const token = signSession(user);
  if (!token) return { error: "Could not create a session.", email };
  (await cookies()).set(SESSION_COOKIE, token, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: SESSION_TTL_S,
  });

  const next = safeNext(formData.get("next"));
  redirect(next && canAccess(user.role, next.split(/[?#]/)[0]) ? next : HOME_FOR_ROLE[user.role]);
}

export async function logout(): Promise<void> {
  (await cookies()).delete(SESSION_COOKIE);
  redirect("/login");
}
