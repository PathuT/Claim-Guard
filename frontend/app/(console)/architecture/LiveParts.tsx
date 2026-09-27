"use client";

import { Fact, ranAt, useSystemFacts } from "@/app/_components/LiveFacts";
import { SystemDiagram } from "./diagrams";

/** Architecture-page figures, read live from GET /system/facts. */

export function LiveHeaderMetrics() {
  const { data: f, error } = useSystemFacts();
  const v = <T,>(get: (x: NonNullable<typeof f>) => T) => (f ? get(f) : error ? null : undefined);
  return (
    <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <Metric
        value={<Fact value={v((x) => `${x.agents.length} + 1`)} />}
        label={<>Agno agents in AgentOS, plus the governed payout, run by the <Fact value={v((x) => x.workflow?.id ?? null)} className="font-mono" /> Workflow</>}
      />
      <Metric value={<Fact value={v((x) => x.rules.length)} />} label="policy rules enforced in code (AGT adapter, rules, token service)" />
      <Metric
        value={<Fact value={v((x) => `≤ ${x.token_ttl_s.max} s`)} />}
        label={<>lifetime of any data credential; <Fact value={v((x) => `${x.token_ttl_s.min} s`)} /> for the most sensitive</>}
      />
      <Metric
        value={<Fact value={v((x) => (x.tests ? `${x.tests.passed}/${x.tests.total}` : null))} />}
        label={<>backend tests passing (last run <Fact value={v((x) => ranAt(x.tests?.ran_at) || null)} />), plus <Fact value={v((x) => x.harbor.scenarios)} /> Harbor scenarios</>}
      />
    </div>
  );
}

function Metric({ value, label }: { value: React.ReactNode; label: React.ReactNode }) {
  return (
    <div className="rounded-md bg-secondary p-3">
      <p className="text-2xl font-semibold tabular-nums text-card-foreground">{value}</p>
      <p className="text-xs text-muted-foreground">{label}</p>
    </div>
  );
}

export function LiveDataSentence() {
  const { data: f, error } = useSystemFacts();
  const v = <T,>(get: (x: NonNullable<typeof f>) => T) => (f ? get(f) : error ? null : undefined);
  return (
    <>
      All data is synthetic: <Fact value={v((x) => x.data.policyholders)} /> policies, <Fact value={v((x) => x.data.claims)} /> claims,{" "}
      <Fact value={v((x) => x.data.hospitals)} /> hospitals (<Fact value={v((x) => x.data.watchlisted_hospitals)} /> watchlisted),{" "}
      <Fact value={v((x) => x.data.policy_clauses)} /> plan clauses embedded with pgvector, and <Fact value={v((x) => x.data.documents)} /> documents,{" "}
      <Fact value={v((x) => x.data.documents_with_hidden_instructions)} /> of which the injection scan flags for hidden instructions. Counted live from Postgres.
    </>
  );
}

export function LiveRules() {
  const { data: f, error } = useSystemFacts();
  if (!f) return <p className="text-sm text-muted-foreground">{error ? "Rules unavailable: is AgentOS running?" : "Loading the rule registry…"}</p>;
  return (
    <>
      <p className="mb-2 text-sm font-semibold text-card-foreground">{f.rules.length} policy rules enforced in code</p>
      <div className="grid gap-1.5 sm:grid-cols-2">
        {f.rules.map((r) => (
          <div key={r.id} className="flex gap-2 rounded-md bg-secondary px-3 py-1.5 text-xs" title={`Enforced by ${r.enforced_by}`}>
            <span className="w-20 shrink-0 font-mono font-semibold text-chart-2">{r.id}</span>
            <span className="text-muted-foreground">{r.must_hold}</span>
          </div>
        ))}
      </div>
      <p className="mt-2 text-[11px] text-muted-foreground">Read from the running code: governance/rules.py&apos;s registry plus the checks the adapter and token service enforce.</p>
    </>
  );
}

const SENSITIVE = new Set(["medical_records", "bank_details", "payments"]);

export function LiveMatrix() {
  const { data: f, error } = useSystemFacts();
  if (!f) return <p className="text-sm text-muted-foreground">{error ? "Scope matrix unavailable: is AgentOS running?" : "Loading the scope matrix…"}</p>;
  const agents = Object.keys(f.scope_matrix);
  const collections = Array.from(new Set(agents.flatMap((a) => f.scope_matrix[a].map((g) => g.scope.split(":")[0])))).sort();
  return (
    <>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[52rem] text-left text-xs">
          <thead>
            <tr className="text-muted-foreground">
              <th className="border-b border-border py-2 pr-3 font-medium">Agent \ collection</th>
              {collections.map((c) => (
                <th key={c} className="border-b border-border py-2 pr-3 font-mono font-medium">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {agents.map((agent) => (
              <tr key={agent}>
                <td className="border-b border-border py-2 pr-3 font-mono font-semibold text-card-foreground">{agent}</td>
                {collections.map((c) => {
                  const grants = f.scope_matrix[agent].filter((g) => g.scope.split(":")[0] === c);
                  return (
                    <td key={c} className="border-b border-border py-2 pr-3">
                      {grants.length ? (
                        grants.map((g) => (
                          <span
                            key={g.scope}
                            title={`token lifetime ${g.ttl_s} s · minimum trust ${g.min_trust}`}
                            className={`mr-1 inline-block rounded px-1.5 py-0.5 font-mono ${SENSITIVE.has(c) ? "bg-destructive/10 text-destructive" : "bg-chart-3/10 text-chart-3"}`}
                          >
                            {g.scope.split(":")[1]} · {g.ttl_s}s
                          </span>
                        ))
                      ) : (
                        <span className="text-muted-foreground/60">—</span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">
        Read live from the token service&apos;s matrix (auth/matrix.py): each cell is a scope an agent may request, with its token lifetime.
        Red cells are the most sensitive collections. Anything not shown is denied (GOV-003).
      </p>
    </>
  );
}

export function LiveSystemDiagram() {
  const { data: f } = useSystemFacts();
  const model = f?.agents.find((a) => a.model)?.model;
  const provider = f?.agents.find((a) => a.provider)?.provider;
  return <SystemDiagram modelLabel={model ? `${provider ?? "LLM"} ${model} · swappable: Gemini, Claude` : undefined} />;
}
