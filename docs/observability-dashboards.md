# Phoenix dashboard views (M6)

docs/architecture.md §11: "Dashboards to prepare in Phoenix: denied actions
by rule, token issuance by agent, latency per agent, cost per claim." Phoenix
(this version) doesn't expose a "saved dashboard" object with its own stable
API — its Traces UI has a per-project filter box (its own Python-expression-
like query language) at the top of the trace table, which is what "prepare a
view" means in practice. Every filter below was run against Phoenix's real
GraphQL API (`spans(filterCondition: "...")`, what the web UI's own filter
box calls) against real spans generated while building M5/M6, and confirmed
to return exactly the expected rows and no others — none of these are
guessed syntax. Bare attribute names (`decision`, not `attributes.decision`
or `attributes['decision']`) are what the filter box actually expects;
`attributes['decision']`-style access also works but `attributes.decision`
(dotted access) does **not** — confirmed by testing all three forms
directly and comparing match counts.

Open a project at `http://localhost:6006`, click into its Traces tab, and
paste a filter into the search box at the top.

## Denied actions, by rule

```
decision == "deny"
```

Every `governance.decision` span (GOV-001/002, PAY-\*, STATE-\*, DATA-\*) and
every gateway `GATEWAY-*` denial sets `decision` to `"deny"` alongside
`rule_id` — so this one filter covers denials from both layers. To narrow to
one rule:

```
decision == "deny" and rule_id == "GOV-001"
```

Group by `rule_id` in the resulting table (click the column header) to see
denial counts per rule — this is the actual "denied actions by rule" view.

## Token issuance, by agent

Run against the **claimguard-token-service** project (or whichever project
a trace's root span landed under — see this doc's note below on Phoenix's
project-grouping behaviour):

```
name == "token.issue" and decision == "allow"
```

Group the result by the `agent_id` attribute to see issuance counts per
agent. Add `and scope == "payments:write"` etc. to narrow to one scope.

## Latency per agent

Every Agno agent run produces its own span (`intake.run`, `medical_
reviewer.run`, `coverage.run`, `fraud.run` — confirmed live), each with a
real `start_time`/`end_time` Phoenix already shows as a duration column in
the Traces table. Filter to isolate one agent:

```
name == "medical_reviewer.run"
```

then sort by the Latency column. No custom span needed — this is exactly
why Agno's OpenInference auto-instrumentation names spans after the agent.

## Cost per claim

Every LLM call span (`Groq.invoke`, confirmed live) carries
`llm.token_count.prompt` and `llm.token_count.completion` — Phoenix's own
per-span cost view multiplies these by the configured per-model price (set
under Settings → Model Pricing) and rolls them up to the trace level
automatically once at least one price is configured. Filter to every span
in one claim's whole trace by its `req_id` (set on the root `claim.flow`
span — see agents/supervisor.py; confirmed live that this same `req_id`
attribute also appears on `governance.decision`/`tool.call` spans within
that trace, so the filter matches more than one row per claim, by design):

```
req_id == "req-<the actual req_id>"
```

For the aggregated per-trace cost total rather than per-span, open that
trace's own detail view (click into any one of the matched spans, then
"View trace") — Phoenix sums cost across every LLM call in the trace there.

## A note on Phoenix's project grouping

Phoenix groups an entire **trace** under whichever project its *root span*
happened to land in — not per-span, by that span's own resource attributes.
Confirmed live while verifying M6's trace propagation: a `token.issue` span
emitted by the token-service process still showed up under the *calling*
process's project (`claimguard-m6-...-test`), not under
`claimguard-token-service`, because the root span (`claim.flow` /
`tool.call`) belonged to the calling process. In practice this means: to see
one claim's whole trace (agent runs, governance decisions, token issuance,
gateway access, all in one place), look in whichever project the calling
process (the supervisor, or a script driving it) was registered under — not
in `claimguard-token-service`/`claimguard-data-gateway`'s own projects,
which mostly show spans from traces *they* rooted (e.g. a direct `curl` to
one of them with no `traceparent` header).
