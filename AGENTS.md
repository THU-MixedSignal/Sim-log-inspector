# Working rules

This repository builds read-only simulation evidence tools. Never launch, stop,
modify or resubmit a simulation. Never alter source logs, PDKs or existing ADC
scripts. Do not infer circuit root causes or add spectral/spur analysis.

Before edits read README.md and plan/v1.md. Keep plan/log.md current. Source
ownership is local to this repository. Use Python standard library first.
Original/private logs, database files and runtime state are ignored by Git.
Fixtures must be sanitized and provenance recorded. No automatic commit/push.

Validation: python -m unittest discover -s tests -v; smoke-test CLI and HTTP;
inspect dashboard; git diff --check. Changes to parsing require positive and
negative regression examples. Unknown/incomplete evidence must never become a
pass. Preserve original severity, text, source location and limitations.

# Operator / new-machine entry point

For setup and read-only operation, start with docs/agent-quickstart.md; SSH
configuration/deployment is in docs/ssh.md. Source invocation from the repository
needs Python 3.10+ only; pip installation is optional. Use examples/real-fixtures.json
for the first self-check. The repository contains no SSH credentials or private
task configuration. Reuse an operator-authorized host alias and request missing
log/work paths; do not guess hosts or bypass host-key verification. The Agent
query/wait contract is docs/agent-handoff.md. Repository links must include the
intended committed revision; uncommitted local edits are not part of a clone.
