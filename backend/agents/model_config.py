"""Shared LLM-client settings for every ClaimGuard agent.

Groq's on-demand tier caps `openai/gpt-oss-120b` at 8,000 tokens per
minute, and one claim uses ~6,600 across intake, medical_reviewer,
coverage and fraud — so two claims inside the same minute (back-to-back
demo runs, or Harbor running scenarios in parallel) hit HTTP 429. Found
live: the 429 surfaced as a plain error string instead of a typed agent
output, the supervisor crashed with a 500, and the claim was left stuck in
`assessing`.

Two layers of retry, both waiting the limit out rather than failing:
- `max_retries`: the Groq SDK's own retry, which honours Groq's
  `retry-after` header ("Please try again in 3.1s");
- `retries` + exponential backoff: Agno's retry of the whole model call on
  a ModelProviderError, for waits longer than the SDK's own budget
  (5 s, 10 s, 20 s).
"""

GROQ_RATE_LIMIT_RETRY = {
    "max_retries": 6,
    "retries": 3,
    "delay_between_retries": 5,
    "exponential_backoff": True,
}
