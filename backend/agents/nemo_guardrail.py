"""Advisory second opinion on document text, on top of the deterministic
marker-list scan (ADR-011). See ADR-013 for the full reasoning.

This module has no access to governance, tokens, the gateway, or the
workflow context — it only classifies text and returns an opinion. It
NEVER decides anything by itself and it can never clear a flag the
marker-list scan already raised (document_guardrail in supervisor.py ORs
the two results together).

Disabled by default (NEMO_GUARDRAILS_ENABLED unset or not "true"), so it
never becomes a hard dependency for `make up`, the test suite, or Harbor.

Uses NVIDIA's nemotron-3.5-content-safety NIM model (NVIDIA_API_KEY) — a
purpose-built safety classifier, called directly as a single chat
completion rather than through NeMo Guardrails' Colang rail machinery
(nemoguardrails 0.24.1's generic "self check input" rail needed a
hand-written policy prompt and its own model, and several general-purpose
NIM chat models were not available on this account — retired (410) or not
provisioned (404). This safety-classifier model was confirmed reachable
and gives a clean, structured verdict ("User Safety: safe"/"unsafe") with
no prompt-engineering required, so the call goes straight to NVIDIA's
OpenAI-compatible endpoint over httpx).

This is scoped to this one classification call only: the six ClaimGuard
agents (agents/model_config.py) are unaffected and keep using
GROQ_API_KEY/GEMINI_API_KEY as before — ADR-001's model-agnostic stance
for the claim pipeline itself is unchanged.

Fails OPEN, not closed: if the NIM call can't be reached or errors, that
means "one fewer opinion for this claim", not "no claim". Invariant 7
(fail closed) governs security-relevant decisions — governance, tokens,
the gateway. This is an optional enhancement sitting before any of those,
and starving it would turn an advisory signal into a new denial-of-service
surface, which is a worse outcome than proceeding on the marker list alone.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

_NIM_CHAT_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
_NIM_SAFETY_MODEL = os.environ.get("NEMO_RAIL_MODEL_ID", "nvidia/nemotron-3.5-content-safety")
_TIMEOUT_SECONDS = 15.0


@dataclass(frozen=True)
class NemoScan:
    flagged: bool
    rationale: str  # human-readable reason, or the error if NeMo could not run


def nemo_enabled() -> bool:
    return os.environ.get("NEMO_GUARDRAILS_ENABLED", "").strip().lower() == "true"


def check_injection(text: str) -> NemoScan:
    """Sends one document's extracted text to the NIM content-safety model
    as a single user turn and reads back its verdict. Never raises: any
    failure (disabled, missing key, provider error, timeout, unexpected
    response shape) is reported as an unflagged scan with the reason in
    `rationale`, so document_guardrail can log it without the claim
    pipeline depending on this call's availability."""
    if not nemo_enabled():
        return NemoScan(flagged=False, rationale="NeMo Guardrails disabled (NEMO_GUARDRAILS_ENABLED != true)")
    if not text.strip():
        return NemoScan(flagged=False, rationale="empty document text")

    api_key = os.environ.get("NVIDIA_API_KEY")
    if not api_key:
        return NemoScan(flagged=False, rationale="NeMo Guardrails unavailable: NVIDIA_API_KEY is not set")

    try:
        response = httpx.post(
            _NIM_CHAT_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": _NIM_SAFETY_MODEL,
                "messages": [{"role": "user", "content": text}],
                "max_tokens": 50,
            },
            timeout=_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        # Verified live against nvidia/nemotron-3.5-content-safety: the
        # model's own reply is the verdict, not a separate structured
        # field — content is exactly "User Safety: safe" or
        # "User Safety: unsafe" (checked against both a clean and a
        # poisoned claim-document sample before wiring this in).
        content = response.json()["choices"][0]["message"]["content"]
        blocked = "unsafe" in content.lower()
        return NemoScan(
            flagged=blocked,
            rationale=f"nemotron-3.5-content-safety verdict: {content.strip()!r}",
        )
    except Exception as exc:  # noqa: BLE001 - fail OPEN (see module docstring), never raise into the workflow
        return NemoScan(flagged=False, rationale=f"NeMo Guardrails unavailable: {type(exc).__name__}: {exc}")


__all__ = ["NemoScan", "check_injection", "nemo_enabled"]
