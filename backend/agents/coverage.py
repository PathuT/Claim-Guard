"""Coverage agent: applies plan terms, calculates payable amount
(docs/security-matrix.md §2: policy_terms:read, claims:read,
policyholders:read_limited). Never sees the discharge summary or medical
records — only medical_reviewer's structured MedicalFinding
(docs/CLAUDE.md invariant 4).

The actual arithmetic lives in settlement.py (plain Python, deterministic —
docs/architecture.md §2). This agent's job is narrower than "compute the
settlement": it takes settlement.py's already-correct CoverageAssessment and
produces a short officer-facing explanation of the reasoning, citing the
same clause_ids the calculator already attached. The LLM never recomputes or
overrides payable_amount, deductions, or clause_ids — those are inputs to
its narration, not outputs it's free to invent.

M4 scope note: this agent takes claim/policy/finding data as plain function
arguments (matching intake.py/medical_reviewer.py's pattern), not via live
tool calls through the data gateway — see docs/plan.md M4 vs. the later
supervisor/tool-call integration work that wires agents to the gateway for
real.
"""

from __future__ import annotations

import os

from agno.agent import Agent
from pydantic import BaseModel

from .schemas import CoverageAssessment

INSTRUCTIONS = """You are the coverage agent for ClaimGuard, a health insurance claims system.

You are given an already-computed settlement (claimed amount, deductions with
clause citations, co-pay, payable amount, flags) — this was calculated by
deterministic code, not by you. Your only job is to write a short,
officer-facing explanation of the reasoning in plain English, one sentence
per deduction citing its clause_id, plus one summary sentence.

Do NOT change, recompute, or contradict any of the given numbers or
clause_ids. Do NOT invent additional deductions or clauses not in the given
data. If you disagree with a number, say so only in your explanation text
(never by changing the structured fields) — the settlement numbers are fixed
inputs to you, not something you calculate.

All amounts are in Indian Rupees. Always write them as ₹ (e.g. ₹37,300),
never $ or USD.
"""


class CoverageExplanation(BaseModel):
    explanation: str


def build_coverage_agent(model_provider: str | None = None) -> Agent:
    provider = model_provider or os.environ.get("MODEL_PROVIDER", "groq")

    if provider == "groq":
        from agno.models.groq import Groq

        model = Groq(id=os.environ.get("MODEL_ID", "openai/gpt-oss-120b"))
    elif provider == "gemini":
        from agno.models.google import Gemini

        model = Gemini(id=os.environ.get("MODEL_ID", "gemini-3.7-flash"))
    # else:
    #     from agno.models.anthropic import Claude

    #     model = Claude(id=os.environ.get("MODEL_ID", "claude-sonnet-5"))

    return Agent(
        name="coverage",
        model=model,
        instructions=INSTRUCTIONS,
        output_schema=CoverageExplanation,
        markdown=False,
    )


def explain_assessment(agent: Agent, assessment: CoverageAssessment) -> str:
    """Runs the narration agent over an already-computed CoverageAssessment
    (from settlement.compute_settlement) and returns its explanation text.
    The assessment itself is never modified here."""
    user_message = assessment.model_dump_json(indent=2)
    response = agent.run(user_message)
    return response.content.explanation
