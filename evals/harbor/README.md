# ClaimGuard Harbor evals (M7)

Runs the 10 scenarios from docs/use-case.md §8 (S01-S10) against the real,
running ClaimGuard AgentOS API, using [Harbor](https://github.com/harbor-framework/harbor)
as the eval runner. See docs/adr/006-evaluation-harbor.md for why Docker is
used here (and nowhere else in this repo — see the root ADRs for the
no-Docker dev-stack decision).

## What each scenario tests

Eight scenarios (S01-S06, S09-S10) submit a real, already-seeded claim to
`POST /claims` and check both:
1. **Outcome** — did the claim reach the expected final state (and, where
   relevant, the expected payable amount / fraud flag types)?
2. **Governance evidence** — does the claim's audit trail
   (`GET /claims/{id}/audit`) show the expected allow/deny pattern by
   rule_id?

Two scenarios (S07, S08) are different: they test real attack attempts
against the governance layer itself (an out-of-matrix scope request, an
expired-token replay), not a claim reaching a particular state. These call
`backend/api/governance_selftest.py`'s probe endpoints directly and check
the probe's own `denied`/`reason_code` fields.

| Scenario | Tests | task_type |
|---|---|---|
| S01 | Straightforward approval, auto-paid | claim |
| S02 | Room-rent cap deduction, routes to human review | claim |
| S03 | Waiting-period denial recommendation | claim |
| S04 | Duplicate-bill fraud flag | claim |
| S05 | Claimed amount vs. real bill mismatch (payable capped at bill total) | claim |
| S06 | Prompt-injection in a discharge summary never affects payout | claim |
| S07 | Coverage agent requesting an out-of-matrix scope (GOV-003) | governance_probe |
| S08 | Expired-token replay against the data gateway (GATEWAY-EXPIRED) | governance_probe |
| S09 | Missing required document -> needs_resubmission | claim |
| S10 | Day-care + watchlisted-hospital double flag | claim |

## Architecture

- `adapter/adapter.py` — custom `harbor.agents.base.BaseAgent`. For a
  `claim_id:`-style task, POSTs to `/claims`. For a `probe_endpoint:`-style
  task (S07/S08), POSTs to that governance self-test endpoint instead. Runs
  from inside Harbor's `main` container, reaching the `backend` sidecar via
  `environment.exec()` + curl over the Compose network (no host-mapped
  port — see each task's `environment/docker-compose.yaml` for why).
- `adapter/verifier.py` — custom `harbor.verifier.base.BaseVerifier`. Reads
  each task's `task.toml` `[metadata]` and re-polls the real backend (claim
  status + audit, or the probe endpoint again) to score outcome +
  governance. One class parameterised by `task.toml`, not ten separate
  verifier classes.
- `docker/backend.Dockerfile` — builds the real `backend/` codebase (same
  code as local dev, not a reimplementation) and runs all three services
  (token service :8100, data gateway :8200, AgentOS :8000) in one container
  via a small inline entrypoint script, seeded fresh per task run.
- `docker/eval.env` — shared, checked-in throwaway secrets (signing keys,
  identity seeds, HMAC key) for every task's isolated backend. Deliberately
  excludes `GROQ_API_KEY` (passed through from the invoking shell) and
  `PHOENIX_COLLECTOR_ENDPOINT` (no per-task Phoenix sidecar).
- `tasks/S0*/` — one directory per scenario: `instruction.md` (what the
  agent is told), `task.toml` (verifier expectations), `environment/`
  (Dockerfile + docker-compose.yaml — identical across all 10 except S07/S08
  share the same template too, since the probe endpoints don't need
  scenario-specific seed data).

## Running

```sh
export GROQ_API_KEY=...   # must be set in the invoking shell; see docker-compose.yaml's ${GROQ_API_KEY}
make eval
```

Equivalent to, run from `evals/harbor/`:

```sh
uv run harbor run \
    --path tasks \
    --agent adapter.adapter:ClaimGuardAgent \
    --verifier adapter.verifier:ClaimGuardVerifier \
    --n-concurrent 1 \
    --yes
```

To run a single scenario instead of all 10:

```sh
uv run harbor run --path tasks/S01 --agent adapter.adapter:ClaimGuardAgent --verifier adapter.verifier:ClaimGuardVerifier --yes
```

`harbor run`'s own summary reports each trial's `outcome`/`governance`/
`mean` reward — M7's "Done when: make eval runs all 10 and reports both
pass rates" is satisfied by the `outcome` and `governance` reward columns
across all 10 trials.

## Verification status

Every scenario's *application logic* — the AgentOS API, the state machine,
the fraud/coverage/settlement agents, the token service, the data
gateway — has been verified by calling the real, running services directly
over HTTP (bypassing Docker entirely), and the exact response shapes
captured there are what `adapter/verifier.py`'s unit tests
(`tests/test_verifier.py`, 15 tests, all passing) assert against.

What has **not** yet been verified on this development machine: an actual
`harbor run` invocation through Docker Compose end-to-end (build the
per-task sandbox, run the adapter inside `main`, run the verifier). Docker
was not detected on this machine as of M7's development (checked via
`docker --version`, `which docker`, and a filesystem search); the
adapter/verifier code itself has been reviewed against harbor==0.23.0's
real installed source rather than left as unverified guesswork, but the
full pipeline (image build, Compose networking, `environment.exec()`
against a live sandbox) is unverified until Docker is available.

Once Docker is confirmed reachable, running `make eval` for just S01 first
(`--include-task-name S01` or `--path tasks/S01`) is the fastest way to
prove the Compose/adapter/verifier wiring end-to-end before running all 10.
