# Demo script — ClaimGuard

About 20 minutes, plus questions. Everything runs on the real stack: real PDF upload,
real LLM agents, real governance, real Postgres, real Harbor evals.

The evaluation criteria are design choices, tech stack, solution architecture, learning
new frameworks, clarity and depth. Each part below says which of those it demonstrates.

## Before the interview

1. Start the stack from the repo root: `npm run dev`. Check that
   `http://localhost:8000/healthz` responds.
2. Run the Harbor suite once so the scoreboard is fresh: `npm run eval`. It takes about
   10 minutes, runs one scenario at a time, and needs no Docker.
3. Rehearse each sample pack once on the Live Run page. It's safe to repeat: each pack
   moves to a fresh, non-overlapping date window, so rehearsals never create a double claim.
4. Use a browser with extensions off (an incognito window works). Open Phoenix
   (`http://localhost:6006`) in a second tab.
5. Wait about a minute between live claim runs. Groq's free tier allows 8,000 tokens a
   minute and one claim uses about 6,600. The agents retry and wait automatically, but
   a run done too soon after another will be visibly slower.

## Part 1: Architecture, 5 min (`/architecture`)

*Demonstrates: solution architecture, design choices, tech stack, depth.*

Use the numbered section bar at the top of the page.

1. **Problem.** "The brief left the problem open. I picked health-insurance claims
   because it combines the three hardest things for AI agents: sensitive medical data,
   irreversible money movement, and documents written by a potential attacker."
2. **Brief → built → beyond.** Go down the table. For each technology in the brief,
   say what was built, then point at the green "Beyond the brief" column.
3. **System architecture.** Walk the five zones left to right, following the numbered
   arrows. Key line: "A request can only move through these zones in order. No
   governance approval, no credential. No credential, no data."
4. **Request lifecycle.** "Two independent layers must both say yes: governance checks
   the action, and the token service plus gateway check the data. A bug in one layer
   still leaves the other."
5. **Design decisions**, only if asked, or pick one. Point out the two "revised while
   building" notes: they show decisions made from evidence, not from a plan.
6. **What we learned.** Pick two or three rows (Agno Team modes, the Phoenix bug, Harbor
   without Docker). This section is the "learning new frameworks" criterion.

## Part 2: Happy path, 3 min (`/live`)

*Demonstrates: Agno agents, JWT RBAC, observability, all live.*

- Click **Jyoti — Dengue fever**, then **bill.pdf**: an ordinary hospital bill.
- Click **Upload & run**. Narrate the chapters on the left while the backend log
  streams on the right:
  - *Intake* reads the documents as untrusted data.
  - *Medical review* is the only agent that sees the diagnosis. It returns ICD-10 A90.
  - *Settlement* is plain Python, not AI: −₹500 and −₹700 under clause 5.G1, so
    **₹37,300** is payable.
  - *Fraud*: point at identity signed → token minted (ttl ≈300 s, jti only) →
    gateway verified the JWT → rows returned.
  - *Tier T2*: governance allows the payout, and it's paid.
- Switch the right panel to **Requirements proof**: every requirement is ticked off by
  evidence from this run.
- Point at the **System flow** boxes that lit up with counts: that's the stack at work.

## Part 3: The attack, 4 min

*Demonstrates: governance and compliance tested in the product.*

- **Rahul — Poisoned discharge summary**. Open **discharge.pdf** first: it looks clean,
  because the attack is white-on-white text.
- **Upload & run.** The log flags "instruction-like text found". The agents ignore it,
  and the claim goes to a human (T3). Nothing is auto-paid.
- "But safety shouldn't depend on the AI resisting a trick." Click **Run the red-team
  attack**. We now pretend an agent obeyed the hidden text:
  - Pay ₹4,50,000 → **PAY-001** denied
  - Right amount to the attacker's account → **PAY-002** denied (account shown as `****6655`)
  - Coverage agent reads medical records → **DATA-001** at governance, and **GOV-003**
    at the token service even if governance were bypassed
  - FlightRecorder hash chain verified.

## Part 4: Human in the loop and audit, 3 min

- `/officer`: open a T3 claim. Show the findings, flags and clauses, but no raw medical
  text. Use break-glass with a reason (audited), then approve. The payout goes through
  the same governed path.
- `/compliance`: every allow and deny system-wide, by rule id.
- Phoenix: search the trace id from the Live Run header. It's one trace across every
  service, with medical text shown as `[REDACTED:medical]`.

## Part 5: Automated evaluation, 1 min (`/live`, bottom)

*Demonstrates: Harbor.*

The **Harbor scoreboard** shows S01–S10, each scored on outcome **and** governance
evidence, run with a custom no-Docker Harbor environment. "Correct isn't enough. The
verifier also checks the audit trail shows the right rules fired."

## Likely questions

- **Why not let an LLM orchestrate?** The sequence and the money maths are
  deterministic code. The LLM is treated as an untrusted decision-maker (see ADR-001's
  revision).
- **Is this really Agno, or Python around it?** It's real Agno: four `Agent`s,
  one `Workflow` (Steps plus a `Condition` for the money branch), served by Agno's
  `AgentOS`. Show `http://localhost:8000/workflows` and `/agents`. The Workflow is
  deliberately deterministic: an Agno Team's LLM leader would cost an extra model call
  per step and let injected text influence the order.
- **Why two layers (AGT and JWT)?** Defence in depth. Governance checks actions, and the
  token service plus gateway check data. The red-team demo shows both refusing the same
  attack.
- **Why no NestJS?** A second backend runtime would add a trust boundary for no
  functional gain (ADR-009).
- **What if the model changes?** Agno is model-agnostic (Groq, Gemini or Claude). Every
  control sits outside the model.
- **How would this go to production?** Swap the token service for an OAuth
  token-exchange server (the claims already mirror it), run Postgres row-level security
  as a complement, containerise with Docker/Kubernetes, move secrets to a vault, and
  put Harbor in CI.
- **How do you know it keeps working?** 80 security tests with no agents involved, plus
  Harbor S01–S10 on every change.
