"use client";

import { useActionState, useState } from "react";
import { type LoginState, login } from "@/app/actions/auth";
import { Icon } from "@/app/_components/Icon";
import { DEMO_ACCOUNTS } from "@/lib/auth/demoAccounts";
import { ROLE_LABEL } from "@/lib/auth/roles";

export function LoginForm({ next }: { next: string }) {
  const [state, formAction, pending] = useActionState<LoginState | undefined, FormData>(login, undefined);
  const [showPassword, setShowPassword] = useState(false);

  return (
    <>
      <form action={formAction} className="mt-6 flex flex-col gap-4">
        <input type="hidden" name="next" value={next} />
        <label className="flex flex-col gap-1.5 text-sm font-medium">
          Work email
          <input
            name="email"
            type="email"
            autoComplete="username"
            required
            key={state?.email ?? "email"}
            defaultValue={state?.email}
            placeholder="you@kaveri-health.example"
            className="h-11 rounded-lg border border-border bg-card px-3 text-sm font-normal shadow-sm outline-none transition focus:border-chart-1 focus:ring-4 focus:ring-chart-1/15"
          />
        </label>
        <label className="flex flex-col gap-1.5 text-sm font-medium">
          Password
          <span className="relative">
            <input
              name="password"
              type={showPassword ? "text" : "password"}
              autoComplete="current-password"
              required
              className="h-11 w-full rounded-lg border border-border bg-card px-3 pr-10 text-sm font-normal shadow-sm outline-none transition focus:border-chart-1 focus:ring-4 focus:ring-chart-1/15"
            />
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              className="absolute inset-y-0 right-0 flex items-center px-3 text-muted-foreground hover:text-foreground"
              aria-label={showPassword ? "Hide password" : "Show password"}
            >
              <Icon name="eye" />
            </button>
          </span>
        </label>

        {state?.error && (
          <p role="alert" className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            <Icon name="alert" className="mt-0.5 h-4 w-4 shrink-0" />
            {state.error}
          </p>
        )}

        <button
          type="submit"
          disabled={pending}
          className="inline-flex h-11 items-center justify-center gap-2 rounded-lg bg-primary text-sm font-semibold text-primary-foreground shadow-sm transition hover:opacity-95 disabled:opacity-60"
        >
          {pending ? "Signing in…" : "Sign in"}
          {!pending && <Icon name="arrowRight" />}
        </button>
        <p className="flex items-center justify-center gap-1.5 text-[11px] text-muted-foreground">
          <Icon name="lock" className="h-3.5 w-3.5" /> Signed, httpOnly session · role-based access to every page
        </p>
      </form>

      <div className="mt-8">
        <div className="flex items-center gap-3">
          <span className="h-px flex-1 bg-border" />
          <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">Demo accounts</span>
          <span className="h-px flex-1 bg-border" />
        </div>
        <ul className="mt-4 flex flex-col gap-2">
          {DEMO_ACCOUNTS.map((account) => (
            <li key={account.email}>
              <form action={formAction}>
                <input type="hidden" name="next" value={next} />
                <input type="hidden" name="email" value={account.email} />
                <input type="hidden" name="password" value={account.password} />
                <button
                  type="submit"
                  disabled={pending}
                  className="group flex w-full items-center gap-3 rounded-lg border border-border bg-card px-3 py-2.5 text-left shadow-sm transition hover:border-chart-1/50 hover:shadow disabled:opacity-60"
                >
                  <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-chart-1/10 text-xs font-semibold text-chart-1">
                    {account.name.split(" ").map((p) => p[0]).join("")}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-2">
                      <span className="text-sm font-medium text-card-foreground">{account.name}</span>
                      <span className="rounded-full bg-secondary px-2 py-0.5 text-[10px] font-medium text-muted-foreground">{ROLE_LABEL[account.role]}</span>
                    </span>
                    <span className="block truncate text-xs text-muted-foreground">{account.blurb}</span>
                  </span>
                  <span className="text-xs font-medium text-chart-1 opacity-0 transition group-hover:opacity-100">Sign in →</span>
                </button>
              </form>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-center text-[11px] text-muted-foreground">
          Demo passwords are shown here on purpose: every person and policy in ClaimGuard is synthetic.
        </p>
      </div>
    </>
  );
}
