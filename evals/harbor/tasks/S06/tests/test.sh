#!/bin/bash
# Placeholder required by harbor's TaskModel.is_valid_dir() directory-shape
# check (evals/harbor's own job invocation always passes a custom
# --verifier at the CLI level, i.e. adapter.verifier:ClaimGuardVerifier,
# which entirely replaces this script at runtime — it is never executed.
# See evals/harbor/README.md for why ClaimGuard uses one shared custom
# verifier instead of a tests/test.sh per task.
exit 0
