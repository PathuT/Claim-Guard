import { redirect } from "next/navigation";
import { AppShell } from "@/app/_components/AppShell";
import { getSessionUser } from "@/lib/auth/session";

/** Every console page: signed in (checked again here, on the server, after
 * proxy.ts), inside the app shell. */
export default async function ConsoleLayout({ children }: { children: React.ReactNode }) {
  const user = await getSessionUser();
  if (!user) redirect("/login");
  return <AppShell user={user}>{children}</AppShell>;
}
