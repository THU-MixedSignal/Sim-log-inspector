# Implementation log

## 2026-11-02 — Initial isolated v0.1

Created E:/spectre-log-inspector Git repository without commit/push. Owned all new
files here; original ADC workspace/logs read-only. Plan: plan/v1.md; detailed
architecture docs/design.md; usage README.md; contract docs/schema.md.

Implemented stdlib Spectre parser, incremental SQLite store, bounded sidecar/ASCII
raw head-tail completeness checks, CLI and localhost HTTP viewer. Five evidence
categories, no circuit cause analysis or spectral work. Single writer transaction,
persistent cursor, generation on replacement/truncation/banner, bounded line/tick,
paginated read-only API. run foreground combines collector+viewer; separate modes
also available. No existing simulation flow altered.

Imported8 sanitized real-log fixtures with provenance. Regression found progress
prefixes attached to R4MEAS, valid-field indexing, Windows connection cleanup and
fixture-redaction issues; fixed before passing22 tests. Benchmarks and Edge UI
validation summarized in docs/validation.md. Current demo private manifest reads
existing locally collected logs, not live remote server. Demo listener127.0.0.1:8765;
PID/start-time recorded in.runtime/viewer-process.json. No scheduled task/service,
no remote changes, no simulation launches/kills. Logs/db/screenshots runtime ignored.

Status: initial version implemented and locally validated within documented scope.
Further simulator formats, full waveforms and ADC oracle plugins remain future work.

Final validation:22 tests pass after adding --open browser convenience. Attempt to restart only the recorded demo viewer process was rejected by automatic policy; no retry/process termination. Existing127.0.0.1:8765 viewer remains live; newest source changes load on next launch. No simulator touched.

## 2026-11-02 — v0.2 concise views

Implemented user-requested separation inside existing SQLite/store/API/UI; no
new service, delegation or approval layer. Evidence indexed by state/problem/
measurement. Latest parser context stored once in cursor. New measurement payloads
omit duplicate fields_raw. Existing DB index upgrade is bounded (128 rows), keeps
evidence IDs and cursor, never deletes source/history. TB explicit FAIL, valid=0
and parse issues are factual problem groups, not an ADC oracle.

Default scan/status and /api/runs now v2 compact summaries. Added problems,
measurements, evidence, details commands/endpoints; old events explicitly remains
debug/export. UI defaults to state and grouped messages, counts/latest measurement;
original text, measurement pages and settings fetched on click. Printed messages
remain distinct from global suppression. No parser/cursor JSON on the main page.

24 tests passed, including 8 real-log cases, stream/group totals, evidence lookup,
generation isolation and old DB compatibility. CLI/HTTP and Edge lazy-loading
checked; no JS errors. Actual 8-run summary ~8.7KB (previous22.3KB); 100 requested
measurements11.9KB (previous raw events82.1KB). Not an RSS benchmark.

New demo on127.0.0.1:8766 with.runtime/summary.sqlite, process identity in
.runtime/summary-viewer-process.json. Old8765 process retained. Stopped only the
newly created, identity-checked summary viewer to relocate it after discovering
Windows allowed both listeners on8765. Added exclusive binding to prevent this.
Source logs/ADC scripts/simulators untouched. No commit/push.

## 2026-11-02 — v0.3 early detection

Review found the tool's purpose is catching problems while a run is still going,
not saving reading; the user confirmed and asked for every review item. Verified
defects fixed: messages inherited stale times (now header-scoped); Spectre notices
were never captured (now kept as NOTICE groups, never escalated); notices-suppressed
totals and per-code suppression were dropped; a non-object state JSON stalled the
whole collector; CLI JSON was GBK on this Windows console and crashed on µ.

Added: transient stop time, per-group phase/first sim time/fraction/first observed
time, manifest watch rules (user policy; the tool only reports matches), baseline
run diff, log-quiet flag, collector heartbeat and offline banner, `wait` for agents
(exit 0 change / 3 timeout / 4 no collector), JSON errors, Host check, port bound
before collection, `--port 0`, measurements tail/before. UI rebuilt around
attention and the simulation-time axis; in-place updates keep focus; browser
notifications merged per run. Schema 3: old databases are rejected untouched, no
migration or v1 layer; /api/events and progress noise events removed.

Fixtures: license search-path host line redacted in all 8 logs (line counts kept,
hashes updated). 6 real logStatus files copied byte-for-byte; compile/license never
produced one. Originals in .runtime/demo.json re-scanned: identical results.

52 tests pass; benchmark 40k events 6.93 s (v0.2 5.82 s). Details in
docs/validation.md. With the user's go-ahead, stopped the two leftover viewers
(PID 22204 v0.1 on 8765, PID 300 on 8766) after re-checking command line and
start time; no simulator touched. Old .runtime/events.sqlite and summary.sqlite
left in place (schema 1/2, now refused).

Committed at the user's request as the repository's first commit (main, no
remote, not pushed). .gitattributes marks tests/fixtures as -text -whitespace:
with core.autocrlf=true a checkout would otherwise rewrite the sanitized logs to
CRLF and break their provenance hashes. The provenance test now rejects any
port@host left in a fixture instead of naming the redacted host.
