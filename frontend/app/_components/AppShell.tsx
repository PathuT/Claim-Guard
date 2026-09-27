"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import useSWR from "swr";
import { logout } from "@/app/actions/auth";
import { getPayoutFreeze } from "@/lib/api";
import { NAV_SECTIONS, ROLE_LABEL, visibleNav } from "@/lib/auth/roles";
import type { SessionUser } from "@/lib/auth/token";
import { BrandMark, Icon } from "./Icon";
import { SessionProvider } from "./SessionContext";

const AGENTOS_URL = process.env.NEXT_PUBLIC_AGENTOS_URL ?? "http://localhost:8000";

async function agentosHealth(): Promise<boolean> {
  try {
    const response = await fetch(`${AGENTOS_URL}/healthz`, { cache: "no-store" });
    return response.ok;
  } catch {
    return false;
  }
}

function initials(name: string): string {
  return name.split(/\s+/).map((part) => part[0]).join("").slice(0, 2).toUpperCase();
}

export function AppShell({ user, children }: { user: SessionUser; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <SessionProvider user={user}>
      <div className="flex min-h-screen">
        {/* Sidebar: fixed on large screens, a drawer on small ones. */}
        <div className={`fixed inset-0 z-30 bg-black/40 lg:hidden ${open ? "block" : "hidden"}`} onClick={() => setOpen(false)} aria-hidden="true" />
        <aside
          className={`fixed inset-y-0 left-0 z-40 flex w-64 flex-col bg-sidebar text-sidebar-foreground transition-transform lg:translate-x-0 ${open ? "translate-x-0" : "-translate-x-full"}`}
        >
          <div className="flex items-center gap-3 px-5 pb-4 pt-5">
            <BrandMark className="h-9 w-9" />
            <div className="leading-tight">
              <p className="text-[15px] font-semibold tracking-tight">ClaimGuard</p>
              <p className="text-[11px] text-sidebar-muted">Kaveri Health Assurance</p>
            </div>
            <button type="button" className="ml-auto rounded p-1 text-sidebar-muted hover:text-sidebar-foreground lg:hidden" onClick={() => setOpen(false)} aria-label="Close menu">
              <Icon name="x" />
            </button>
          </div>
          <Suspense fallback={<nav className="flex-1" />}>
            <SidebarNav user={user} onNavigate={() => setOpen(false)} />
          </Suspense>
          <div className="border-t border-sidebar-border p-3">
            <div className="flex items-center gap-3 rounded-lg px-2 py-2">
              <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-chart-1/25 text-xs font-semibold text-sidebar-foreground ring-1 ring-sidebar-border">
                {initials(user.name)}
              </span>
              <div className="min-w-0 flex-1 leading-tight">
                <p className="truncate text-sm font-medium">{user.name}</p>
                <p className="truncate text-[11px] text-sidebar-muted">{ROLE_LABEL[user.role]}</p>
              </div>
              <form action={logout}>
                <button type="submit" className="rounded-md p-2 text-sidebar-muted transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground" title="Sign out" aria-label="Sign out">
                  <Icon name="logout" />
                </button>
              </form>
            </div>
          </div>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col lg:pl-64">
          <TopBar user={user} onMenu={() => setOpen(true)} />
          <main className="mx-auto flex w-full max-w-[1440px] flex-1 flex-col px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
            <Suspense fallback={null}>
              <DeniedNotice />
            </Suspense>
            {children}
          </main>
          <footer className="border-t border-border px-4 py-3 text-center text-[11px] text-muted-foreground sm:px-8">
            ClaimGuard · synthetic data only (fictional insurer, hospitals and people) · Agno · Microsoft AGT · EdDSA JWT · Arize Phoenix · Harbor
          </footer>
        </div>
      </div>
    </SessionProvider>
  );
}

function SidebarNav({ user, onNavigate }: { user: SessionUser; onNavigate: () => void }) {
  const pathname = usePathname();
  const sections = visibleNav(user.role);
  return (
    <nav className="flex-1 overflow-y-auto px-3 pb-4">
      {sections.map((section) => (
        <div key={section.title} className="mt-4 first:mt-1">
          <p className="px-3 pb-1.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-sidebar-muted">{section.title}</p>
          <ul className="flex flex-col gap-0.5">
            {section.items.map((item) => {
              const active = !item.external && !item.href.includes("#") && (item.href === "/" ? pathname === "/" : pathname.startsWith(item.href));
              const cls = `group flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors ${
                active ? "bg-sidebar-accent font-medium text-sidebar-foreground" : "text-sidebar-muted hover:bg-sidebar-accent/60 hover:text-sidebar-foreground"
              }`;
              const inner = (
                <>
                  <span className={active ? "text-chart-1" : "text-sidebar-muted group-hover:text-sidebar-foreground"}>
                    <Icon name={item.icon} />
                  </span>
                  <span className="flex-1">{item.label}</span>
                  {item.external && <Icon name="external" className="h-3.5 w-3.5 opacity-60" />}
                </>
              );
              return (
                <li key={item.href} title={item.description}>
                  {item.external ? (
                    <a href={item.href} target="_blank" rel="noopener noreferrer" className={cls}>
                      {inner}
                    </a>
                  ) : (
                    <Link href={item.href} className={cls} onClick={onNavigate} aria-current={active ? "page" : undefined}>
                      {inner}
                    </Link>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}

function pageTitle(pathname: string): string {
  for (const section of NAV_SECTIONS) {
    for (const item of section.items) {
      if (item.external || item.href.includes("#")) continue;
      if (item.href === "/" ? pathname === "/" : pathname.startsWith(item.href)) return item.label;
    }
  }
  return "ClaimGuard";
}

function TopBar({ user, onMenu }: { user: SessionUser; onMenu: () => void }) {
  const pathname = usePathname();
  const { data: healthy } = useSWR("agentos-health", agentosHealth, { refreshInterval: 15_000 });
  const { data: freeze } = useSWR(healthy ? "payout-freeze-topbar" : null, getPayoutFreeze, { refreshInterval: 15_000 });
  return (
    <header className="sticky top-[env(safe-area-inset-top,0px)] z-20 border-b border-border bg-background/85 backdrop-blur">
      <div className="mx-auto flex h-14 w-full max-w-[1440px] items-center gap-3 px-4 sm:px-6 lg:px-8">
        <button type="button" className="rounded-md p-1.5 text-muted-foreground hover:bg-secondary lg:hidden" onClick={onMenu} aria-label="Open menu">
          <Icon name="menu" className="h-5 w-5" />
        </button>
        <div className="flex min-w-0 items-center gap-2 text-sm">
          <span className="hidden text-muted-foreground sm:inline">Console</span>
          <span className="hidden text-muted-foreground sm:inline">/</span>
          <span className="truncate font-semibold text-foreground">{pageTitle(pathname)}</span>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <StatusPill ok={healthy === true} pending={healthy === undefined} label={healthy === false ? "Backend offline" : "Agents online"} />
          {freeze && <StatusPill ok={!freeze.frozen} label={freeze.frozen ? "Payouts frozen" : "Payouts active"} />}
          <span className="hidden rounded-full border border-border px-2.5 py-1 text-[11px] font-medium text-muted-foreground md:inline">Synthetic data</span>
          <span className="hidden text-xs text-muted-foreground xl:inline">{user.title}</span>
        </div>
      </div>
    </header>
  );
}

function StatusPill({ ok, pending, label }: { ok: boolean; pending?: boolean; label: string }) {
  const dot = pending ? "bg-muted-foreground" : ok ? "bg-success" : "bg-destructive";
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-2.5 py-1 text-[11px] font-medium text-card-foreground">
      <span className={`h-1.5 w-1.5 rounded-full ${dot} ${ok && !pending ? "animate-pulse" : ""}`} />
      {pending ? "Checking…" : label}
    </span>
  );
}

function DeniedNotice() {
  const denied = useSearchParams().get("denied");
  if (!denied) return null;
  return (
    <div className="mb-5 flex items-center gap-2 rounded-lg border border-warning/40 bg-warning/10 px-4 py-2.5 text-sm text-card-foreground">
      <Icon name="lock" className="h-4 w-4 text-warning" />
      Your role can&apos;t open <span className="font-mono">{denied}</span>, so you were brought to your home page. Console pages are role-based, like the agents&apos; scopes.
    </div>
  );
}
