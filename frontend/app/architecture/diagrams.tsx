/** Architecture diagrams for the /architecture page, as inline SVG so they
 * follow the console's light/dark theme tokens (fill-card, stroke-border…)
 * and stay sharp on a projector. Pure presentational server components. */

type Tone = "default" | "agent" | "control" | "data" | "danger" | "external" | "code";

const TONE: Record<Tone, { box: string; title: string }> = {
  default: { box: "fill-card stroke-border", title: "fill-card-foreground" },
  agent: { box: "fill-chart-1/10 stroke-chart-1/60", title: "fill-card-foreground" },
  control: { box: "fill-chart-2/10 stroke-chart-2/60", title: "fill-card-foreground" },
  data: { box: "fill-chart-3/10 stroke-chart-3/60", title: "fill-card-foreground" },
  danger: { box: "fill-destructive/10 stroke-destructive/60", title: "fill-destructive" },
  external: { box: "fill-secondary stroke-border", title: "fill-card-foreground" },
  code: { box: "fill-success/10 stroke-success/60", title: "fill-card-foreground" },
};

function Box({
  x, y, w, h, title, lines = [], tone = "default", dashed = false,
}: {
  x: number; y: number; w: number; h: number; title: string; lines?: string[]; tone?: Tone; dashed?: boolean;
}) {
  const t = TONE[tone];
  return (
    <g>
      <rect x={x} y={y} width={w} height={h} rx={7} className={`${t.box} stroke-[1.2]`} strokeDasharray={dashed ? "5 4" : undefined} />
      <text x={x + 10} y={y + 19} className={`${t.title} text-[12.5px] font-semibold`}>
        {title}
      </text>
      {lines.map((line, i) => (
        <text key={i} x={x + 10} y={y + 35 + i * 14} className="fill-muted-foreground text-[10.5px]">
          {line}
        </text>
      ))}
    </g>
  );
}

function Zone({ x, y, w, h, label }: { x: number; y: number; w: number; h: number; label: string }) {
  return (
    <g>
      <rect x={x} y={y} width={w} height={h} rx={10} className="fill-secondary/40 stroke-border" strokeDasharray="3 4" />
      <text x={x + 10} y={y - 8} className="fill-muted-foreground text-[10.5px] font-semibold uppercase tracking-wider">
        {label}
      </text>
    </g>
  );
}

function Arrow({ d, id, label, lx, ly, dashed = false, danger = false }: {
  d: string; id: string; label?: string; lx?: number; ly?: number; dashed?: boolean; danger?: boolean;
}) {
  return (
    <g>
      <path d={d} fill="none" className={danger ? "stroke-destructive" : "stroke-foreground/60"} strokeWidth={1.4} strokeDasharray={dashed ? "5 4" : undefined} markerEnd={`url(#${id})`} />
      {label && lx != null && ly != null && (
        <text x={lx} y={ly} className={`${danger ? "fill-destructive" : "fill-chart-1"} text-[10.5px] font-semibold`}>
          {label}
        </text>
      )}
    </g>
  );
}

function Markers({ id }: { id: string }) {
  return (
    <defs>
      <marker id={id} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
        <path d="M0,0 L10,5 L0,10 z" className="fill-foreground/60" />
      </marker>
    </defs>
  );
}

/** The whole system: five trust zones left→right, from untrusted input to
 * restricted data, with the numbered path a claim takes. */
export function SystemDiagram() {
  const m = "sys-arrow";
  return (
    <div className="overflow-x-auto">
      <svg viewBox="0 0 1180 700" className="min-w-[980px]" role="img" aria-label="ClaimGuard system architecture">
        <Markers id={m} />

        <Zone x={10} y={40} w={175} h={525} label="People & untrusted input" />
        <Zone x={200} y={40} w={175} h={525} label="Presentation" />
        <Zone x={390} y={40} w={335} h={525} label="Agent runtime · Agno AgentOS" />
        <Zone x={740} y={40} w={215} h={525} label="Control plane · AGT" />
        <Zone x={970} y={40} w={200} h={525} label="Data plane · restricted" />

        {/* People */}
        <Box x={20} y={70} w={155} h={58} title="Policyholder" lines={["Priya · uploads bill +", "discharge summary PDFs"]} />
        <Box x={20} y={146} w={155} h={58} title="Claims officer" lines={["Arjun · decides T3 cases,", "audited break-glass"]} />
        <Box x={20} y={222} w={155} h={58} title="Compliance officer" lines={["Divya · audit log,", "denials, reports"]} />
        <Box x={20} y={298} w={155} h={58} title="Platform engineer" lines={["Phoenix traces,", "Harbor eval results"]} />
        <Box x={20} y={374} w={155} h={58} title="Attacker" tone="danger" lines={["Rahul · poisoned PDF,", "duplicate / inflated bills"]} />
        <Box x={20} y={470} w={155} h={72} title="Harbor eval runner" tone="code" lines={["S01–S10 replayed", "as automated tests", "(no Docker)"]} />

        {/* Console */}
        <Box
          x={210} y={70} w={155} h={470} title="Next.js Console"
          lines={["TypeScript · App Router", "", "• Architecture", "• Live Run (SSE stream)", "• Policyholder", "• Officer (T3 queue)", "• Compliance", "• Agent Pipeline", "", "No NestJS BFF —", "calls the APIs directly", "(ADR-009)"]}
        />

        {/* Agent runtime */}
        <Box x={400} y={62} w={315} h={48} title="LLM provider (external)" tone="external" dashed lines={["Groq gpt-oss-120b · swappable: Gemini, Claude"]} />
        <Box x={400} y={124} w={315} h={48} title="Agno Workflow — claim-assessment" tone="code" lines={["Steps + 2 guardrails + Condition (T2 pay / T3 human)"]} />
        <Box x={400} y={186} w={152} h={62} title="Intake" tone="agent" lines={["Agno · typed output", "docs = untrusted data"]} />
        <Box x={563} y={186} w={152} h={62} title="Medical reviewer" tone="agent" lines={["Agno · ONLY agent that", "sees medical text"]} />
        <Box x={400} y={260} w={152} h={62} title="Coverage" tone="agent" lines={["Agno · explains the", "settlement, can't change it"]} />
        <Box x={563} y={260} w={152} h={62} title="Fraud" tone="agent" lines={["Agno · pseudonymised", "data + hospital watchlist"]} />
        <Box x={400} y={334} w={152} h={62} title="Settlement + tiers" tone="code" lines={["deterministic Python", "clause per deduction"]} />
        <Box x={563} y={334} w={152} h={62} title="Payout" tone="code" lines={["Condition branch · one", "governed money call"]} />
        <Box x={400} y={416} w={315} h={48} title="Officer decision API (FastAPI)" lines={["human approve / partial / reject → governed payout"]} />
        <Box x={400} y={478} w={315} h={62} title="Claim intake API (FastAPI)" lines={["real PDF upload · pypdf text extraction", "sha256 fingerprints · live SSE event stream"]} />

        {/* Control plane */}
        <Box x={750} y={62} w={195} h={100} title="AGT governance adapter" tone="control" lines={["on EVERY tool call:", "GOV-001/002/004 · PAY-001…006", "STATE-001/002 · DATA-001/002", "trusted context · fail closed"]} />
        <Box x={750} y={186} w={195} h={48} title="Claim state machine" tone="control" lines={["every transition governed"]} />
        <Box x={750} y={248} w={195} h={62} title="FlightRecorder (AGT)" tone="control" lines={["append-only audit log", "hash-chained, verifiable"]} />
        <Box x={750} y={334} w={195} h={122} title="Token service (FastAPI)" tone="control" lines={["Ed25519 identity · ID-001", "trust score gate · TRUST-001", "scope matrix · GOV-003", "EdDSA JWT: 1 agent, 1 scope,", "1 claim, ≤ 300 s · JWKS", "revoke by jti / req_id"]} />

        {/* Data plane */}
        <Box x={980} y={62} w={180} h={128} title="Data gateway (FastAPI)" tone="data" lines={["7-step JWT validation", "row binding to the claim", "field allowlists", "HMAC pseudonymisation", "only holder of DB creds"]} />
        <Box x={980} y={214} w={180} h={142} title="Postgres 16 + pgvector" tone="data" lines={["Supabase · 9 collections:", "policyholders, bank_details,", "policy_terms (embedded),", "claims, claim_documents,", "medical_records, hospitals,", "payments (mock), audit"]} />
        <Box x={980} y={380} w={180} h={62} title="Payments = mock ledger" tone="data" lines={["no real money path", "payments:write, 60 s token"]} />

        {/* Observability band */}
        <Box
          x={390} y={600} w={780} h={70} title="OpenTelemetry → Arize Phoenix (self-hosted)" tone="external"
          lines={["custom spans (governance, token, gateway) + OpenInference for Agno · W3C trace context across 3 services = ONE trace per claim", "redaction processor BEFORE export: medical text → [REDACTED:medical], account numbers → last 4 digits"]}
        />

        {/* Flow arrows */}
        <Arrow id={m} d="M175,99 L210,99" />
        <Arrow id={m} d="M175,175 L210,175" />
        <Arrow id={m} d="M175,251 L210,251" />
        <Arrow id={m} d="M175,403 L210,403" danger dashed />
        <Arrow id={m} d="M365,150 L400,148" label="1" lx={372} ly={140} />
        <Arrow id={m} d="M365,440 L400,440" />
        <Arrow id={m} d="M365,509 L400,509" />
        <Arrow id={m} d="M175,530 C250,600 350,600 420,540" dashed label="evals → API" lx={232} ly={596} />
        <Arrow id={m} d="M715,205 L750,120" label="2 · tool call" lx={652} ly={182} />
        <Arrow id={m} d="M715,372 L750,400" label="3 · identity → JWT" lx={606} ly={410} />
        <Arrow id={m} d="M715,291 L732,291 L732,174 L960,174 L980,150" label="4 · Bearer JWT" lx={790} ly={170} />
        <Arrow id={m} d="M1070,190 L1070,214" label="5 · SQL" lx={1078} ly={206} />
        <Arrow id={m} d="M945,140 C962,180 962,240 945,279" dashed label="6 · audit" lx={890} ly={244} />
        <Arrow id={m} d="M715,160 C728,190 735,205 750,210" />

        {/* Spans into Phoenix */}
        <Arrow id={m} d="M560,565 L560,600" dashed />
        <Arrow id={m} d="M848,565 L848,600" dashed label="7 · spans" lx={856} ly={588} />
        <Arrow id={m} d="M1070,565 L1070,600" dashed />
      </svg>
    </div>
  );
}

type SeqStep =
  | { kind: "msg"; from: number; to: number; label: string; reply?: boolean; tag?: string }
  | { kind: "note"; lane: number; lines: string[]; tone?: "control" | "data" };

const LANES = ["Agent (e.g. fraud)", "AGT adapter", "FlightRecorder", "Token service", "Data gateway", "Postgres"];
const LANE_X = [95, 300, 505, 710, 915, 1110];

const STEPS: SeqStep[] = [
  { kind: "msg", from: 0, to: 1, label: "tool call: search_claims_pseudonymised", tag: "1" },
  { kind: "note", lane: 1, tone: "control", lines: ["GOV-001 tool allowlist", "GOV-002 call budget (40)", "PAY/STATE/DATA rules vs", "TRUSTED context, not args"] },
  { kind: "msg", from: 1, to: 2, label: "append allow/deny (hash-chained)", tag: "2" },
  { kind: "msg", from: 1, to: 0, label: "allow — or structured denial + rule id", reply: true, tag: "3" },
  { kind: "msg", from: 0, to: 3, label: "Ed25519-signed identity assertion + scope + req_id", tag: "4" },
  { kind: "note", lane: 3, tone: "control", lines: ["ID-001 signature, ≤ 30 s old", "GOV-003 agent × scope matrix", "TRUST-001 trust threshold", "delegation never widens"] },
  { kind: "msg", from: 3, to: 0, label: "EdDSA JWT · 1 scope · 1 claim · ttl ≤ 300 s · jti", reply: true, tag: "5" },
  { kind: "msg", from: 0, to: 4, label: "POST /query · Authorization: Bearer <JWT>", tag: "6" },
  { kind: "note", lane: 4, tone: "data", lines: ["signature/kid · aud/iss", "exp (5 s skew) · jti revoked?", "scope · row binding", "→ field allowlist"] },
  { kind: "msg", from: 4, to: 5, label: "SELECT", tag: "7" },
  { kind: "msg", from: 4, to: 0, label: "allowlisted, pseudonymised rows only", reply: true, tag: "8" },
];

// Vertical layout of the steps, computed once: notes are taller than messages.
const STEP_TOPS = STEPS.reduce<number[]>((tops, s, i) => {
  const prev = i === 0 ? 92 : tops[i - 1] + (STEPS[i - 1].kind === "note" ? 78 : 40);
  return [...tops, prev];
}, []);
const SEQ_HEIGHT = STEP_TOPS[STEP_TOPS.length - 1] + (STEPS[STEPS.length - 1].kind === "note" ? 78 : 40) + 20;

/** One governed data access, end to end — the path every agent read and
 * write takes. Each hop also emits an OpenTelemetry span (not drawn). */
export function SequenceDiagram() {
  const m = "seq-arrow";
  const laid = STEPS.map((s, i) => ({ s, top: STEP_TOPS[i] }));
  const height = SEQ_HEIGHT;

  return (
    <div className="overflow-x-auto">
      <svg viewBox={`0 0 1200 ${height}`} className="min-w-[980px]" role="img" aria-label="Sequence of one governed tool call">
        <Markers id={m} />
        {LANES.map((lane, i) => (
          <g key={lane}>
            <rect x={LANE_X[i] - 80} y={16} width={160} height={40} rx={7} className={`${i === 0 ? "fill-chart-1/10 stroke-chart-1/60" : i <= 3 ? "fill-chart-2/10 stroke-chart-2/60" : "fill-chart-3/10 stroke-chart-3/60"} stroke-[1.2]`} />
            <text x={LANE_X[i]} y={41} textAnchor="middle" className="fill-card-foreground text-[12px] font-semibold">
              {lane}
            </text>
            <line x1={LANE_X[i]} y1={56} x2={LANE_X[i]} y2={height - 10} className="stroke-border" strokeWidth={1.2} strokeDasharray="4 4" />
          </g>
        ))}
        {laid.map(({ s, top }, i) => {
          if (s.kind === "note") {
            const x = LANE_X[s.lane] + 8;
            return (
              <g key={i}>
                <rect x={x} y={top} width={184} height={66} rx={6} className={`${s.tone === "data" ? "fill-chart-3/10 stroke-chart-3/50" : "fill-chart-2/10 stroke-chart-2/50"}`} />
                {s.lines.map((line, j) => (
                  <text key={j} x={x + 8} y={top + 16 + j * 14} className="fill-card-foreground text-[10.5px]">
                    {line}
                  </text>
                ))}
              </g>
            );
          }
          const x1 = LANE_X[s.from];
          const x2 = LANE_X[s.to];
          const ay = top + 22;
          const dir = x2 > x1 ? -1 : 1;
          return (
            <g key={i}>
              <path d={`M${x1},${ay} L${x2 + dir * 4},${ay}`} className={s.reply ? "stroke-foreground/50" : "stroke-foreground/70"} strokeWidth={1.4} strokeDasharray={s.reply ? "5 4" : undefined} markerEnd={`url(#${m})`} fill="none" />
              <text x={(x1 + x2) / 2} y={ay - 6} textAnchor="middle" className="fill-card-foreground text-[11px]">
                <tspan className="fill-chart-1 font-semibold">{s.tag}. </tspan>
                {s.label}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

const STATES: { id: string; x: number; y: number; tone: Tone }[] = [
  { id: "submitted", x: 20, y: 95, tone: "default" },
  { id: "needs_resubmission", x: 20, y: 185, tone: "danger" },
  { id: "assessing", x: 215, y: 95, tone: "agent" },
  { id: "auto_approved", x: 425, y: 35, tone: "code" },
  { id: "pending_human", x: 425, y: 155, tone: "control" },
  { id: "approved", x: 640, y: 105, tone: "code" },
  { id: "approved_partial", x: 640, y: 155, tone: "code" },
  { id: "rejected", x: 640, y: 205, tone: "danger" },
  { id: "paid", x: 850, y: 35, tone: "code" },
];

const W = 160;
const H = 34;

function edgePoint(id: string, side: "l" | "r" | "t" | "b") {
  const s = STATES.find((st) => st.id === id)!;
  if (side === "l") return [s.x, s.y + H / 2];
  if (side === "r") return [s.x + W, s.y + H / 2];
  if (side === "t") return [s.x + W / 2, s.y];
  return [s.x + W / 2, s.y + H];
}

/** docs/architecture.md §8, as enforced by api/state_machine.py. */
export function StateDiagram() {
  const m = "state-arrow";
  const edge = (a: string, as: "l" | "r" | "t" | "b", b: string, bs: "l" | "r" | "t" | "b") => {
    const [x1, y1] = edgePoint(a, as);
    const [x2, y2] = edgePoint(b, bs);
    const mx = (x1 + x2) / 2;
    return as === "b" || as === "t" ? `M${x1},${y1} L${x2},${y2}` : `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`;
  };
  return (
    <div className="overflow-x-auto">
      <svg viewBox="0 0 1030 260" className="min-w-[860px]" role="img" aria-label="Claim state machine">
        <Markers id={m} />
        <Arrow id={m} d={edge("submitted", "r", "assessing", "l")} />
        <Arrow id={m} d={edge("submitted", "b", "needs_resubmission", "t")} label="missing document" lx={108} ly={160} />
        <Arrow id={m} d={edge("assessing", "r", "auto_approved", "l")} label="T2 · auto" lx={360} ly={62} />
        <Arrow id={m} d={edge("assessing", "r", "pending_human", "l")} label="T3 · human" lx={356} ly={168} />
        <Arrow id={m} d={edge("auto_approved", "r", "paid", "l")} label="PAY rules pass" lx={660} ly={44} />
        <Arrow id={m} d={edge("pending_human", "r", "approved", "l")} />
        <Arrow id={m} d={edge("pending_human", "r", "approved_partial", "l")} />
        <Arrow id={m} d={edge("pending_human", "r", "rejected", "l")} label="officer only" lx={590} ly={250} />
        <Arrow id={m} d={edge("approved", "r", "paid", "l")} />
        <Arrow id={m} d={edge("approved_partial", "r", "paid", "l")} />
        {STATES.map((s) => (
          <g key={s.id}>
            <rect x={s.x} y={s.y} width={W} height={H} rx={17} className={`${TONE[s.tone].box} stroke-[1.2]`} />
            <text x={s.x + W / 2} y={s.y + 21} textAnchor="middle" className={`${TONE[s.tone].title} font-mono text-[11.5px] font-semibold`}>
              {s.id}
            </text>
          </g>
        ))}
        <text x={850} y={110} className="fill-muted-foreground text-[10.5px]">
          <tspan x={850} dy={0}>No edge assessing → rejected:</tspan>
          <tspan x={850} dy={14}>only a human can reject</tspan>
          <tspan x={850} dy={14}>(STATE-001). Tokens for the</tspan>
          <tspan x={850} dy={14}>request are revoked on entering</tspan>
          <tspan x={850} dy={14}>pending_human, paid, rejected.</tspan>
        </text>
      </svg>
    </div>
  );
}
