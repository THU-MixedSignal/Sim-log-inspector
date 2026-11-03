# Native Spectre fixtures, 2026-11-03

14 new managed Spectre 21.1.0.509.isr12 runs: normal RC, seven intentional
input/numerical failures, two output-cap stops (one intended wall timeout hit
the output cap first), SOA, explicit TB messages, and A/B three-frame ADC runs.
Tests replay these logs only; they never launch a simulator.

Logs are line-preserving sanitized copies: account, host, environment/model/run
paths and license endpoints redacted; diagnostic codes, severity, measurement
values and times retained. State JSON contains selected observed execution and
resource fields. logStatus and the small generic RC raw are byte-exact copies.
Hashes and source run IDs are in provenance.json. No PDK/model source is included.

The wall-limit case proves output_size_limit with exit0, not a wall timeout.
Do not replace the native observations with the intended failure category.
The IC-phase first SOA messages do not report simulation time; later groups do.
Explicit TB FAIL/PASS lines have native progress dots/digits before them.

See docs/live-spectre-validation.md and tests/test_live_spectre.py.
