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
