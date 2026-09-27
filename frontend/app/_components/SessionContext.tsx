"use client";

import { createContext, useContext } from "react";
import type { SessionUser } from "@/lib/auth/token";

const SessionContext = createContext<SessionUser | null>(null);

export function SessionProvider({ user, children }: { user: SessionUser; children: React.ReactNode }) {
  return <SessionContext.Provider value={user}>{children}</SessionContext.Provider>;
}

/** The signed-in console user (null only outside the console layout). */
export function useSessionUser(): SessionUser | null {
  return useContext(SessionContext);
}
