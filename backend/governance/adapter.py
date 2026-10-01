"""The AGT governance adapter: every agent tool call passes through
`check_and_audit()` before it executes (docs/engineering-guide.md invariant 1, ADR-002).

Wraps AGT's real `agent_control_plane.FlightRecorder` for the hash-chained
audit log (docs/engineering-guide.md invariant 10) and implements the GOV/PAY/STATE/DATA
rules (plus GOV-004, the compliance payout kill switch — ADR-012) from
docs/security-matrix.md §8 as plain Python predicates in
governance/rules.py (see ADR-002's "Integration approach" section for why we
did not register them with AGT's PolicyEngine.add_custom_rule() directly —
our own orchestration needed richer per-rule denial reasons than a bare bool).

Critical invariant (security-matrix.md §8): "input.context values are fetched
by the AGT adapter from trusted stores, never from the agent's arguments."
`ToolCallContext` below is built by the caller (the supervisor/API layer)
from claims/assessment/payment records already in Postgres — never from the
tool call's own `args` — so a prompt-injected argument can request anything
but can only be *checked against* trusted values, never supply them.

Known gap (tracked, not silently missing): `ctx.args` is passed to
FlightRecorder.start_trace() as-is, so a payout's real account_ref currently
lands unredacted in the audit log. docs/plan.md M6 owns redaction ("no
medical text or account numbers in spans") — that scope should extend to
this audit log too, not just OTel spans, when M6 is built.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from opentelemetry import trace

from observability.live_events import emit

from .controls import read_payout_freeze
from .flight_recorder import get_recorder
from .rules import RuleResult, run_all_rules
from .tool_allowlist import TOOL_CALL_BUDGET_PER_REQUEST, tool_allowed

tracer = trace.get_tracer("claimguard.governance")

# GOV-002: per-request tool-call budget (circuit breaker). Keyed by req_id,
# reset only by process restart in M3 — a real deployment would expire
# these; for a single local-dev process this is enough to prove the rule.
_tool_call_counts: dict[str, int] = {}


@dataclass
class ToolCallContext:
    """Everything a policy rule might need, assembled by the caller from
    trusted stores (never from the tool call's own arguments — see module
    docstring). `trusted` holds the specific values PAY/STATE/DATA rules
    check the agent's *requested* args against."""

    req_id: str
    agent_id: str
    tool_name: str
    args: dict[str, Any]
    claim_id: str | None = None
    input_prompt: str | None = None
    # Trusted context, fetched by the caller from Postgres/gateway — never
    # from `args`. Only the keys a given rule needs must be populated;
    # absence is treated as "can't confirm this is safe" -> deny, per
    # docs/engineering-guide.md invariant 7 (fail closed).
    trusted: dict[str, Any] = field(default_factory=dict)


class GovernanceDenied(Exception):
    def __init__(self, rule_id: str, message: str) -> None:
        self.rule_id = rule_id
        self.message = message
        super().__init__(f"{rule_id}: {message}")


def check_and_audit(ctx: ToolCallContext) -> str:
    """The one function every agent tool call must go through
    (docs/engineering-guide.md invariant 1). Raises GovernanceDenied on any policy
    failure; returns the audit trace_id (FlightRecorder's own id for this
    decision) on success. Always writes an audit entry via FlightRecorder
    and a `governance.decision` span, on both the allow and deny path.

    M5: the return value changed from None to the trace_id (existing
    callers that ignored the return value are unaffected) because
    execute_payout needs a real `agt_decision_id` to record on the
    payments row (docs/architecture.md §10) — the audit trace_id already
    *is* that decision id; inventing a second, separate one would just be
    two ids for the same governance decision.
    """
    recorder = get_recorder()
    # `input_prompt` is FlightRecorder's own free-text metadata field (never
    # populated by any agent here — see ToolCallContext.input_prompt's own
    # default of None), so it's used to carry req_id/claim_id instead of
    # folding them into tool_args, which would corrupt tool_args' actual
    # meaning ("what the tool call's real arguments were") for anyone
    # reading the audit log later. Needed so a caller (e.g. the Harbor
    # verifier, evals/harbor/adapter/verifier.py) can filter this claim's
    # own audit entries out of the full log — FlightRecorder.query_logs()
    # has no claim_id/req_id filter of its own (confirmed against the real
    # agent_control_plane API), only agent_id/policy_verdict/time range.
    audit_marker = f"req_id={ctx.req_id}" + (f" claim_id={ctx.claim_id}" if ctx.claim_id else "")
    trace_id = recorder.start_trace(agent_id=ctx.agent_id, tool_name=ctx.tool_name, tool_args=ctx.args, input_prompt=audit_marker)

    with tracer.start_as_current_span("governance.decision") as span:
        span.set_attribute("agent_id", ctx.agent_id)
        span.set_attribute("tool_name", ctx.tool_name)
        span.set_attribute("req_id", ctx.req_id)
        if ctx.claim_id:
            span.set_attribute("claim_id", ctx.claim_id)

        # GOV-001: tool not in this agent's allowlist -> deny before anything else.
        if not tool_allowed(ctx.agent_id, ctx.tool_name):
            result = RuleResult(rule_id="GOV-001", allowed=False, reason=f"tool {ctx.tool_name!r} not in {ctx.agent_id!r}'s allowlist")
            _deny(recorder, trace_id, span, result, ctx)
            raise GovernanceDenied(result.rule_id, result.reason)

        # GOV-002: per-request tool-call budget (circuit breaker).
        _tool_call_counts[ctx.req_id] = _tool_call_counts.get(ctx.req_id, 0) + 1
        if _tool_call_counts[ctx.req_id] > TOOL_CALL_BUDGET_PER_REQUEST:
            result = RuleResult(
                rule_id="GOV-002", allowed=False,
                reason=f"tool-call budget ({TOOL_CALL_BUDGET_PER_REQUEST}) exceeded for req_id {ctx.req_id!r}",
            )
            _deny(recorder, trace_id, span, result, ctx)
            raise GovernanceDenied(result.rule_id, result.reason)

        # GOV-004 (compliance kill switch): the freeze state is fetched here,
        # from the trusted controls store, on every execute_payout check —
        # and it REPLACES any "payout_freeze" the caller put in `trusted`,
        # so no caller (let alone an agent's args) can claim "not frozen".
        # A new dict rather than mutating the caller's own object.
        if ctx.tool_name == "execute_payout":
            freeze = read_payout_freeze()
            ctx.trusted = {**ctx.trusted, "payout_freeze": freeze}
            span.set_attribute("payout_freeze", freeze.frozen)

        # GOV-004, PAY-*, STATE-*, DATA-* rules — each is a no-op (returns allowed=True)
        # for tool calls it doesn't apply to (e.g. PAY rules skip anything
        # that isn't execute_payout).
        for result in run_all_rules(ctx):
            if not result.allowed:
                _deny(recorder, trace_id, span, result, ctx)
                raise GovernanceDenied(result.rule_id, result.reason)

        span.set_attribute("decision", "allow")
        recorder.log_success(trace_id)
        span.set_attribute("audit_trace_id", trace_id)
        emit(
            "governance",
            f"AGT policy check ALLOW — {ctx.agent_id} → {ctx.tool_name}",
            f"GOV-001 allowlist ✓ · GOV-002 budget {_tool_call_counts[ctx.req_id]}/{TOOL_CALL_BUDGET_PER_REQUEST} · "
            f"{'GOV-004 payout freeze ✓ · ' if ctx.tool_name == 'execute_payout' else ''}"
            f"PAY/STATE/DATA rules ✓ · audit entry {trace_id[:8]} appended to hash-chained FlightRecorder",
            level="success",
            data={"agent_id": ctx.agent_id, "tool_name": ctx.tool_name, "audit_id": trace_id},
        )
        return trace_id


def _deny(recorder, trace_id: str, span, result: RuleResult, ctx: ToolCallContext) -> None:
    span.set_attribute("decision", "deny")
    span.set_attribute("rule_id", result.rule_id)
    span.set_attribute("audit_trace_id", trace_id)
    recorder.log_violation(trace_id, f"{result.rule_id}: {result.reason}")
    emit(
        "governance",
        f"AGT policy check DENY — {result.rule_id}",
        f"{result.reason} · audit entry {trace_id[:8]} appended to hash-chained FlightRecorder",
        level="deny",
        data={"rule_id": result.rule_id, "audit_id": trace_id, "agent_id": ctx.agent_id, "tool_name": ctx.tool_name},
    )
