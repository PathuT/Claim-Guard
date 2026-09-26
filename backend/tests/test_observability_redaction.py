"""Invariant test for the redaction processor (docs/plan.md M6: "Redaction
processor + test (no medical text or account numbers in spans)";
docs/architecture.md §11: "Tested by an invariant test.").

Tests the pure `redact_value()` function directly — no live Phoenix
collector needed, matching this repo's existing pattern of unit-testing the
pure logic behind a span/HTTP boundary separately from the live integration
checks done by hand during each milestone (see test_security_data_gateway.py
etc.). The live check that a real span's attributes land redacted in
Phoenix's own storage (not just that the pure function behaves) was run
directly against a running Phoenix instance while this was built; this file
is the automated, repeatable half of that verification.
"""

from __future__ import annotations

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from observability.redaction import (
    MEDICAL_REDACTED,
    RedactionSpanProcessor,
    redact_value,
)


def _emit_span(attributes: dict) -> dict:
    """Builds a throwaway TracerProvider with RedactionSpanProcessor
    registered BEFORE an InMemorySpanExporter (same ordering
    tracing.setup_tracing() uses for the real Phoenix exporter), emits one
    span with the given attributes, and returns what actually landed in the
    exporter — i.e. what a real collector would have received."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(RedactionSpanProcessor())
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test")
    with tracer.start_as_current_span("test.span") as span:
        for key, value in attributes.items():
            span.set_attribute(key, value)
    (exported,) = exporter.get_finished_spans()
    return dict(exported.attributes)


def test_medical_free_text_fully_redacted():
    assert redact_value("diagnosis_text", "Dengue fever (NS1 positive)") == MEDICAL_REDACTED
    assert redact_value("history", "Pre-existing hypertension, on medication") == MEDICAL_REDACTED
    assert redact_value("treatment", "IV fluids, antipyretics") == MEDICAL_REDACTED
    assert redact_value("notes_for_officer", "Platelet trend consistent with dengue admission.") == MEDICAL_REDACTED


def test_openinference_input_output_value_treated_as_medical():
    """The actual live risk this test guards against: OpenInference's Agno
    auto-instrumentation captures an agent's raw input/output under these
    exact attribute keys (confirmed by reading
    openinference/instrumentation/agno/_runs_wrapper.py directly) — for
    medical_reviewer/intake, that's the raw diagnosis text / discharge
    summary, not just a generic string."""
    raw = "Diagnosis: Dengue fever (NS1 positive) with thrombocytopenia. Patient: Priya Raman."
    assert redact_value("input.value", raw) == MEDICAL_REDACTED
    assert redact_value("output.value", "icd10: A90") == MEDICAL_REDACTED


def test_account_number_reduced_to_last_four_digits():
    redacted = redact_value("account_ref", "50010052816993")
    assert redacted == "****6993"
    assert "50010052816993" not in redacted


def test_account_number_embedded_in_longer_string_still_redacted():
    redacted = redact_value("some_message", "Paying to account 50010052816993 now")
    assert "50010052816993" not in redacted
    assert redacted.endswith("****6993 now")


def test_known_persona_names_pseudonymised():
    assert redact_value("policyholder_name", "Priya Raman") == "PSEUDO-PERSON-A"
    assert redact_value("policyholder_name", "Rahul Verma") == "PSEUDO-PERSON-B"
    # Consistent (same input -> same pseudonym), matching the pseudonymisation
    # discipline docs/architecture.md §10 already establishes for claims.
    assert redact_value("x", "Priya Raman") == redact_value("y", "Priya Raman")


def test_name_embedded_in_longer_string_still_redacted():
    # A non-medical-keyed attribute (unlike input.value/output.value, which
    # are always fully replaced regardless of content) — this is what
    # actually exercises the name-redaction path rather than the medical
    # full-replacement path taking precedence.
    redacted = redact_value("some_message", "Claim submitted by Rahul Verma at Lakeview Clinic")
    assert "Rahul Verma" not in redacted
    assert "PSEUDO-PERSON-B" in redacted


def test_non_string_values_pass_through_unchanged():
    """A span attribute can be an int, bool, or a tuple (OTel allows
    homogeneous sequences) — redact_value must not choke on or mis-redact
    non-string types, since none of the three rules apply to them."""
    assert redact_value("rows_returned", 42) == 42
    assert redact_value("decision", True) is True
    assert redact_value("some_list", (1, 2, 3)) == (1, 2, 3)


def test_unrelated_string_attribute_left_alone():
    """A plain req_id/scope/rule_id-style attribute — the majority of this
    codebase's hand-rolled span attributes (see governance/adapter.py,
    data_gateway/app.py) — must pass through untouched, not be mangled by
    an over-eager digit or name regex."""
    assert redact_value("req_id", "req-abc123") == "req-abc123"
    assert redact_value("rule_id", "PAY-001") == "PAY-001"
    assert redact_value("scope", "claims:read_pseudonymised") == "claims:read_pseudonymised"


def test_llm_system_message_content_left_readable():
    """Found live while checking a real trace: the per-message breakdown
    OpenInference's Groq/Agno instrumentation adds to the LLM call span
    (llm.input_messages.<N>.message.content) is a second copy of the same
    content input.value/output.value already redact — but index 0 is
    always this agent's own fixed system prompt (no per-claim data at all),
    and redacting it too would only make a trace harder to debug for no
    privacy benefit. Exercised through a real span + RedactionSpanProcessor,
    not just redact_value in isolation, since the role-conditional decision
    needs the sibling .message.role attribute on the same span."""
    exported = _emit_span({
        "llm.input_messages.0.message.role": "system",
        "llm.input_messages.0.message.content": "You are the medical reviewer agent for ClaimGuard.",
        "llm.input_messages.1.message.role": "user",
        "llm.input_messages.1.message.content": "Diagnosis: Dengue fever (NS1 positive). Patient: Priya Raman.",
        "llm.output_messages.0.message.role": "assistant",
        "llm.output_messages.0.message.content": '{"icd10": "A90"}',
    })
    assert exported["llm.input_messages.0.message.content"] == "You are the medical reviewer agent for ClaimGuard."
    assert exported["llm.input_messages.1.message.content"] == MEDICAL_REDACTED
    assert exported["llm.output_messages.0.message.content"] == MEDICAL_REDACTED


def test_redaction_runs_before_export_on_a_real_span():
    """End-to-end confirmation (not just the pure function): a span built
    with input.value/output.value/account_ref/a known name, run through the
    real RedactionSpanProcessor -> exporter pipeline in that order, lands in
    the exporter already redacted — the same thing verified by hand against
    a live Phoenix instance while this was built (see the milestone's own
    notes), now automated."""
    exported = _emit_span({
        "input.value": "Diagnosis: Dengue fever (NS1 positive). Patient: Priya Raman.",
        "output.value": "stay_justified: true",
        "account_ref": "50010052816993",
        "req_id": "req-redaction-test-001",
    })
    assert exported["input.value"] == MEDICAL_REDACTED
    assert exported["output.value"] == MEDICAL_REDACTED
    assert exported["account_ref"] == "****6993"
    assert exported["req_id"] == "req-redaction-test-001"
