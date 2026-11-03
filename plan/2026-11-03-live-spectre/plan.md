# Live Spectre validation — 2026-11-03

User explicitly authorizes real Spectre simulations and deliberate input faults.
This overrides the repository's no-launch operator rule for this bounded test
campaign only; simcheck itself remains a read-only observer. Use the existing
ADC project's managed launcher, never add simulator control to the product.

Own: this plan, docs/live-spectre-validation.md, new sanitized fixtures and their
focused regression, private .runtime/live-spectre-20261103, and fixes to parser/
integrity/store only if native evidence demonstrates a defect. Existing dirty
README/docs/design/docs/validation/plan/log/web files belong to prior UI work;
preserve their changes. Append concise results to shared plan/log only.

Remote runs and local ADC input ownership are declared in its separate plan.
Read-only: original ADC circuits, historical results, PDKs, standard libraries,
OA, user notes, credentials and unrelated processes. No commit or push.

Test normal RC completion; syntax/model/include/parameter/AHDL faults; topology,
DC/transient convergence; printed terminal limits and suppression; TB normal/
invalid/malformed/FAIL records; output and wall limits; a few normal ADC frames.
Do not manufacture missing error types by editing logs. Retain unsuccessful
fault-injection attempts and untested/queued cases. Avoid inducing system OOM,
global disk exhaustion, swap or shared-license outages; historical fixtures
cover these when no safe live reproduction exists.

Check status/show/evidence against native excerpts, state/logStatus and hashes;
observe at least one in-progress change with wait; check measurement separation,
footer/exit conflicts and UI/API. Use bounded incremental log mirroring if the
server lacks Python >=3.10. The mirror is an external test adapter, not a tool
feature. Resource gates apply; queued is not executed.
