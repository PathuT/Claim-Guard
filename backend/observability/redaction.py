"""Redaction processor (docs/architecture.md §11): "span attributes and LLM
input/output captured in Phoenix pass through a redaction processor: medical
free text -> [REDACTED:medical], account numbers -> last 4 digits, names ->
pseudonym."

Implemented as an OTel `SpanProcessor`, registered via `add_span_processor()`
in `tracing.setup_tracing()` — one processor per exported span, running
before whatever exporter Phoenix's `register()` already wired up, so nothing
downstream (Phoenix's own storage, its UI) ever sees the raw values. This is
necessary because two different kinds of attribute need catching:

1. Hand-rolled span attributes this codebase sets itself (governance/
   adapter.py, data_gateway/app.py, auth/app.py, api/officer.py) — today
   none of these carry raw medical text or account numbers directly (spot-
   checked: only ids, scopes, decisions, rule_ids, counts), but a future
   attribute added by mistake (e.g. `span.set_attribute("account_ref", ...)`)
   is exactly the kind of thing this processor exists to catch even when a
   developer forgets to redact it by hand at the call site — defense in
   depth, not "trust every call site to remember."
2. OpenInference's Agno auto-instrumentation, which captures the RAW agent
   input/output as `input.value`/`output.value` span attributes — this is
   the actual live risk: medical_reviewer's `input.value` contains the raw
   diagnosis text (docs/CLAUDE.md invariant 4 is about which *agents* may
   read medical data, not about what ends up in a trace export), and
   intake's contains the raw bill/discharge summary text. The LLM call span
   ITSELF (`Groq.invoke`/etc., separate from the agent-level span) carries a
   second, more granular copy of the same content under
   `llm.input_messages.<N>.message.content` and
   `llm.output_messages.<N>.message.content` (one attribute per chat
   message) — found live while checking a real trace: `input.value`/
   `output.value` were correctly redacted, but this per-message breakdown
   was not, since it wasn't in the original fixed key list.

   This per-message breakdown is handled differently from every other rule
   here: index 0 of `llm.input_messages` is always this agent's system
   prompt (confirmed live: role is always "system" at index 0, "user" at
   index 1+) — the agent's own fixed instructions, identical across every
   claim, containing no per-claim data at all. Redacting it too would only
   make a trace harder to debug for no privacy benefit, so `on_end()` below
   reads each message's sibling `...message.role` attribute and only
   redacts `.message.content` for "user"/"assistant" roles, not "system".

Redaction rules, applied to every string attribute value on every span
(mutating ReadableSpan._attributes in place — OTel's public API has no
"amend an attribute" method for a SpanProcessor, so this reaches into the
same internal field every real-world OTel redaction processor does):
  - Medical free text -> "[REDACTED:medical]" (whole-value replacement, not
    partial: docs/architecture.md's own wording is "medical free text ->
    [REDACTED:medical]", not a partial mask, since there's no safe partial
    disclosure of a diagnosis the way there is for an account number).
  - A bare account/bank-account-shaped number -> its last 4 digits
    (`****1234`), matching bank-statement convention.
  - A name known to this process — the fixed Priya/Rahul fixtures' names,
    which are the only names this system ever generates deterministically
    (docs/use-case.md's personas) — -> a stable, non-reversible pseudonym.
    General synthetic names from Faker are not attempted at all here: they
    are already synthetic ("no real people... ever", README) and this
    catches the two names the codebase's own docs/tests reference directly.
"""

from __future__ import annotations

import re

from opentelemetry.attributes import BoundedAttributes
from opentelemetry.sdk.trace import ReadableSpan, Span
from opentelemetry.sdk.trace.export import SpanProcessor

MEDICAL_REDACTED = "[REDACTED:medical]"

# Attribute keys that may carry raw agent input/output (OpenInference's own
# semantic-convention names) or medical free text set by hand elsewhere.
_MEDICAL_ATTRIBUTE_KEYS = {"input.value", "output.value", "diagnosis_text", "history", "treatment", "notes_for_officer"}

# A bare 9-18 digit run is treated as an account-number shape (matches the
# seeded bank_details.account_number format — see
# data/synthetic/generators/reference_data.py's "500100"+8 digits pattern).
_ACCOUNT_NUMBER_RE = re.compile(r"\b\d{9,18}\b")

# The two fixed persona names from docs/use-case.md — see module docstring
# for why this doesn't attempt to catch arbitrary Faker-generated names too.
_KNOWN_NAMES = {"Priya Raman": "PSEUDO-PERSON-A", "Rahul Verma": "PSEUDO-PERSON-B"}

# Matches "llm.input_messages.0.message.content" / "llm.output_messages.2.message.content"
# etc. — captures the matching "...message.role" key so on_end() can check
# it before deciding whether this particular message counts as medical.
_LLM_MESSAGE_CONTENT_RE = re.compile(r"^(llm\.(?:input|output)_messages\.\d+)\.message\.content$")


def _llm_message_role_key(content_key: str) -> str | None:
    """"llm.input_messages.0.message.content" -> "llm.input_messages.0.message.role",
    or None if `content_key` doesn't match that shape at all."""
    m = _LLM_MESSAGE_CONTENT_RE.match(content_key)
    if m is None:
        return None
    return f"{m.group(1)}.message.role"


def _redact_account_numbers(value: str) -> str:
    return _ACCOUNT_NUMBER_RE.sub(lambda m: f"****{m.group(0)[-4:]}", value)


def _redact_names(value: str) -> str:
    for name, pseudonym in _KNOWN_NAMES.items():
        value = value.replace(name, pseudonym)
    return value


def redact_value(key: str, value: object) -> object:
    """Pure function, unit-tested directly (observability/redaction.py's
    own test) as well as exercised indirectly through a live span — applies
    all three rules in order: medical text is a full replacement (and skips
    the other two rules, since there's nothing left to redact), otherwise
    account-number and name redaction both apply to whatever string
    remains.

    Does NOT handle the `llm.*.message.content` role-conditional case (see
    module docstring) — that needs a second attribute on the same span
    (the sibling `.message.role`) to decide, which a single (key, value)
    pair can't express; `RedactionSpanProcessor.on_end()` handles that case
    itself, over the whole attribute set, before falling back to this
    function for everything else.
    """
    if not isinstance(value, str):
        return value
    if key in _MEDICAL_ATTRIBUTE_KEYS:
        return MEDICAL_REDACTED
    return _redact_names(_redact_account_numbers(value))


class RedactionSpanProcessor(SpanProcessor):
    """Registered before the exporting processor Phoenix's own `register()`
    sets up (see tracing.setup_tracing) so redaction happens exactly once,
    in this process, before a span is ever serialised and sent to the
    collector — not a viewer-side masking that would still leave the raw
    value sitting in Phoenix's own storage.
    """

    def on_start(self, span: Span, parent_context=None) -> None:
        return None

    def on_end(self, span: ReadableSpan) -> None:
        attributes = span._attributes
        if not attributes:
            return

        redacted: dict[str, object] = {}
        for key, value in attributes.items():
            role_key = _llm_message_role_key(key)
            if role_key is not None and isinstance(value, str):
                # A per-message llm.*.message.content attribute: only
                # redact when the sibling role is user/assistant, not
                # system (see module docstring) — bypasses redact_value's
                # ordinary key-based lookup entirely for this one case.
                role = attributes.get(role_key)
                redacted[key] = MEDICAL_REDACTED if role in ("user", "assistant") else value
            else:
                redacted[key] = redact_value(key, value)

        # BoundedAttributes (this SDK version's real backing type for
        # ReadableSpan._attributes) enforces its own immutability once a
        # span has ended, guarding even direct __setitem__ — so redaction
        # replaces the whole attributes object with a new BoundedAttributes
        # built from the redacted values, rather than mutating the
        # existing one in place, which OTel would otherwise reject.
        span._attributes = BoundedAttributes(
            maxlen=attributes.maxlen,
            attributes=redacted,
            immutable=True,
            max_value_len=attributes.max_value_len,
        )

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True
