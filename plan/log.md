# Implementation log

## 2026-11-03 — Native-review follow-ups: meter, frames, tags, generations, phases

The user asked me to commit the live campaign work first, then fix the five issues its review found. Read README.md, plan/v1.md and the collector design notes first. The pending work was committed on branch `live-spectre-fixes`, not pushed:
- 6a81db9: run close/save, export and compact rows;
- 0070c84: native fixtures and the five live fixes.

The five fixes, with their native evidence:
- **Progress meter.** Spectre's 70-cell progress meter is read as the longest exact prefix within the current analysis. It resets at each analysis banner. It is also read from an unfinished last line, which is not indexed. It is reported as `meter` when it is ahead of the logged time. In native adc-a-tt the meter is the only progress after the transient starts (31/50/70 cells). In the noise run it is never more than 0.76 points ahead of the testbench frame time.
- **Frame counts.** `frames.n` counts only parsed R4MEAS frames; the other testbench lines are counted as `other`. Native tb-records is now 3+3, not 6. The dashboard's measurement count and reload check use n+other.
- **Uncoded tags.** An uncoded tag is native only when it is indented inside a Spectre header block; coded tags are native anywhere. Outside a block it becomes `TB:reported_<word>`, keeping its raw text and line. The 4 native uncoded FATAL lines all sit inside blocks.
- **Older-generation evidence.** It carries `latest_gen`. The cursor's `file_generation` separates an appended attempt (path:line still valid) from a replaced file (`replaced`; path:line refers to the earlier content). A cursor written before this field existed counts as replaced.
- **Analysis phases.** Analyses are named from banners (Transient, DC, AC, Monte Carlo) and from the first `during … analysis` clause in headers. Within known DC/AC/MC analyses, "time =" solver statistics no longer set the simulation time. details only lists stops for transient analyses.

Store compatibility: old cursors get the newly added parser state keys filled with defaults. Schema 3 is unchanged. API 4 only gains keys, apart from the meaning of `frames.n`.

Validation:
- 100 unittest pass; node --check and git diff --check pass.
- Old and new parser emit identical events on all 22 real repository logs.
- A read-only aggregate over 210 local native DC/AC/MC logs: footer agreement 210/210; native error counts unchanged; 0 uncoded tags outside blocks; 821 problem events moved from setup to their analysis.
- A live-collector demo in `.runtime/followups-20261103/` checked CLI, HTTP and wait: a log replacement woke wait with exit 0, and the old evidence was marked.
- Dashboard checked at 1280×820 and 375×812. Fixed the timeline SVG `hidden` property, which never applied.

I tried to import three sanitized native DC/AC/Monte Carlo logs from another local project as fixtures. The permission check refused, because the user had not named that source and destination. Nothing was copied; the tests use hand-written minimal lines and the import awaits the user's decision. No simulation actions and no source-log edits. Committed on `live-spectre-fixes` at the user's request; not pushed.

## 2026-11-03 — User-authorized native Spectre campaign

Prepared16 isolated managed cases under the ADC project's separate scoped plan;
14 have executed and been hash-checked/collected, syntax and no-output wall-time
case remain CPU-queued. Input/numerical faults are deliberate. Original circuits,
PDK/OA/history unchanged. A/B three-frame TT decks preserve frozen DUT/TB/library/
observer hashes; codes231/44/183, reported_valid1 each. B retains five CMI groups.
No ADC performance/electrical qualification is inferred.

New real evidence exposed5 defects: no-log queued/rejected state discarded;
expected_stop metadata wrongly required unconfigured raw; failure diagnostic
statistics rewound progress to0; progress-prefixed FAIL/PASS dropped; rule summary
skipped the first untimed IC warning. Fixed in existing parser/integrity/store,
kept unknown time/partial evidence conservative.14 sanitized native fixtures,
5 focused campaign regression methods plus boundary cases. Full suite85 passed;
CLI/API and actual Edge UI lazy evidence/measurement operations passed.

RC54,470B raw inspected and its truncated copy/wrong analysis correctly fail
completeness. Output cap tests show native failure despite process exit0. Initial
wall timeout attempt hit file cap first and is recorded as coverage miss, not
wall proof. License/swap/system OOM were not deliberately induced. Native SOA
stream replay wait: partial line did not wake, complete line->wait0.224s, offline
collector->exit4. This is local replay latency, not a remote simulator latency.

User authorized one1-thread CPU exception, applied only to queued rc-normal;
other completed cases naturally passed original gates. One other queued worker
temporarily identity-paused (no simulation child), then resumed. Exact original
policy SHA256 restored2b600b9ce3eebaa611e924c8d7cc5cc4e11a0c211d20302b91f4e6307eb2ddfb.
No local management sources/policy changed. Tool remains read-only; the explicit
user simulation authorization is scoped to this test campaign only.

Report docs/live-spectre-validation.md. Private work.runtime/live-spectre-20261103
contains receipts, source bindings and current campaign-status.json. Test viewer
127.0.0.1:50147 uses validated.sqlite; finite mirror/collection checkpoint helpers
retain queued results without resubmission, no recurring automation. Existing
unrelated UI/export/docs changes preserved, not claimed as this task. No commit/push.

## 2026-11-03 — Close and save sidebar runs

User requested closing sidebar history entries and saving them; explicitly chose
both HTML and JSON. Read README.md and plan/v1.md. Add sibling save/close buttons
without changing compact problem rows. Closing is reversible browser-local
hiding, remembered for the current generation, with a restore entry and sensible
selection/focus when the selected or last open run is closed. Keep collection
and source evidence intact. Save through a read-only download endpoint: a
consistent SQLite snapshot, HTML offline report or JSON with current-generation
stored events, original text/severity/locations and coverage limits. Validate
exports, escaping/error paths, read-only behavior, UI close/restore/persistence,
desktop/narrow appearance, CLI/HTTP and the full suite. No simulation actions,
source-log edits or commit/push.

Implemented sibling ↓/× actions, a two-format save menu, generation-scoped local
history hiding and Restore closed; mobile uses the same actions by the picker.
Preserve the selected run when another is closed; choose the next open run when
needed and focus Restore when none remain. Rechecked persistence after reload,
all six closed/restored, menu arrows/Escape, mobile focus and overflow. Adjusted
menu bounds to clientWidth so the scrollbar does not clip the right edge.

Read-only /api/export prepares an atomic download from one SQLite transaction,
spooling over 1 MiB to disk and sending Content-Length. JSON includes every stored
current-generation event; HTML provides problems/checks and the same complete
stored evidence. Source text, locations, severity, suppression and coverage limits
remain intact; filenames/HTML are escaped. No source files need to be present.

Validation: current full checkout passes 79 unittest tests, including eight new
export/interface checks. 6 CLI commands, 16 HTTP requests, six evidence lookups
and all exported events checked against original sanitized source lines. Native
browser menu downloaded HTML and JSON successfully. 1440×850 and 375×812 UI
inspected; console clean. HTML download/static content verified; local file URL
rendering is unavailable under the in-app browser URL policy and was not bypassed.
Artifacts: .runtime/ui-history-20261103/ (unittest-final.txt, smoke.json, browser-check.json,
demo-warning.html/json, export-http.html/json, dashboard.jpg, mobile.jpg).
Updated README/schema/design/plan. Restarted only this task's known read-only
serve process on 127.0.0.1:55921 (current PID 39536). Preserved unrelated parallel
parser/integrity/store changes. No simulation actions, source edits or commit/push.

## 2026-11-03 — Restore the original compact row layout

User supplied the preferred original screenshot and rejected the extra stacked
layout/cards. Read README.md and plan/v1.md. Restore severity, identifier, count,
time/percentage, tags and message to one desktop row; change hierarchy through
type size/color only. Restore expansion to First/Last plus source path followed
directly by original log lines. Remove added facts/detail cards and repeated
labels. Keep English, white theme, colored outlined tags, native evidence and
keyboard focus behavior. Limit wrapping to narrow layouts. No parser, collector,
CLI/API, source-log or simulation changes; no commit/push.

Validated: 68 unittest tests, node --check and git diff --check pass; 6 CLI
commands and 14 HTTP requests pass, including six original evidence records.
Browser inspected all five expanded groups at 1440×850 and 375×812 with no
horizontal page overflow and no facts/detail cards. Desktop identifier, count,
time, tag area and body share column positions; body is 15px dark, count/time
12px gray. Rule/baseline tooltip details, First/Last, suppression line and focus
remain available. No console errors. Reused localhost viewer. Artifacts in
.runtime/ui-compact-20261103/: unittest-final.txt, smoke.json, browser-check.json,
all-expanded.jpg, mobile-expanded.jpg, dashboard.jpg and problem-row.jpg.

## 2026-11-03 — Align problem rows and expanded evidence

User requested fixed positions for tags and gray metadata and a review of every
expanded row. Read README.md and plan/v1.md first. Replace content-sized flex
positions with shared grids for identifier/body and count/time/tag slots; keep
empty slots so missing data does not shift other fields. Preserve red Rule and
amber baseline tags, English, white theme, critical states and original evidence.
Organize expansion into consistent facts, rule/reference details, source controls
and raw text. All five demo problem groups were opened and inspected together,
including single/multiple records, untimed evidence and suppression. Desktop
1100×820 and narrow 375×812 keep identifiers/messages/tags aligned with no page
overflow; expanded facts, source paths and raw boxes share positions. Keyboard
First/Last and measurement evidence retain focus and original text. English,
white theme and critical states remain intact.

Validated: 68 unittest tests, node --check and git diff --check pass; 6 CLI and
14 HTTP smoke checks pass, including all six first/last source evidence records
and failed/unknown/incomplete states. Reused the existing localhost viewer.
Artifacts: .runtime/ui-alignment-20261103/ (unittest-final.txt, smoke.json,
all-expanded.jpg, mobile-expanded.jpg, dashboard.jpg). Updated usage/design and
validation notes. No parser, collector, CLI/API or source-log changes. No commit/push.

## 2026-11-03 — Restore outlined status tags

User asked to restore the colored tag outlines, especially the red Rule tag.
Read README.md and plan/v1.md first. Restore compact outlined chips (red Rule,
amber baseline/difference/warning, blue New) while retaining the problem-first
layout, small metadata, English and white theme. No header rule lists or other
duplicate information restored. Collection, evidence and CLI/API unchanged.

Validated: 68 unittest tests, node --check, CLI/HTTP smoke and git diff --check
pass. Inspected desktop/narrow page: Rule has a red outline, Not in baseline
an amber outline, both remain 12px below 15px problem prose; no horizontal
overflow at 375px. Existing local viewer refreshed; preview saved under
.runtime/ui-tags-20261103/. No simulation changes or commit/push by this task.

## 2026-11-03 — Authorized GitHub publication

User explicitly asked to organize and commit all current changes, publish the
repository to GitHub and provide an Agent link/SSH onboarding prompt. This
authorizes this publication; the no-automatic-commit/push rule otherwise remains.
Read README.md and plan/v1.md. Confirmed GitHub connector/CLI login chenzc24.
Created https://github.com/chenzc24/spectre-log-inspector as PRIVATE and added
origin after confirming the name was unused. The connector lacks repository
creation, so used authenticated gh; pushes use local Git.

Reviewed only application/docs/sanitized fixtures and tests; .claude/ is now
ignored and runtime/private/DB/build outputs stay local. Added concrete source
URLs and docs/agent-prompt.md. First two commits: 4c53938 examples/interface
regression; 0daa650 packaging and repository/Agent/SSH onboarding. Current
validation: 68 tests pass, 7 CLI checks over 14 runs, 11 HTTP checks, offline
wheel build/asset verification, node --check and diff checks. Browser verified
current problem-first desktop layout and expanded native severity/rules/
suppression/source evidence; no console errors. Reviewed 103 historical blobs
and current candidate files for credential patterns without printing contents;
no hits or private/runtime payload files. Audit .runtime/github-publish-0ktlyzy2/.

Pushed main and verified PRIVATE visibility/default branch main. Third grouped
commit 6c04eac contains the dashboard and validation records. Cloned that exact
revision from GitHub HTTPS into a clean external path with spaces, removed
source-path environment overrides and used Python -S (no pip/site-packages):
import came from the new checkout, 14 example states matched, and all 68 tests
passed. Result: github-clone.json and github-clone-unittest.txt in the audit dir.
The parallel UI task then completed outlined Rule/baseline tag styling; reviewed
and included it in a final follow-up with this publication record. Node syntax,
desktop display, original severity/evidence and console checks remain clean.
Private repository access must be authorized on the receiving Agent's machine.
No simulator or real SSH task is part of this publication.

## 2026-11-03 — Problem-first dashboard hierarchy

User approved the UI audit: remove repeated information, quiet auxiliary text,
prioritize problem prose, retain English/white theme, critical states and raw
evidence, and show the finished page. Read README.md and plan/v1.md first.
Implemented within dashboard resources and usage/validation notes: one collector
status, no header rule list or repeated problem totals, progress next to its
timeline, 15px problem prose with width priority, 12px gray metadata below it.
Single printed occurrences omit repetitive x1. Expanded evidence includes native
severity, printed/suppressed count scope, first time, rule names, baseline and
unchanged source lines/path. First/Last and measurement View/Hide retain keyboard
focus. Sidebar explicitly shows actual Failed/Unknown/Incomplete states. Narrow
screens use a native run selector; its grid row stays 56px rather than stretching
into unused screen height. English, white theme and all concurrent work retained.
Collection/parser/CLI/API unchanged; no source log or simulation changes.

Validation: final 68 unittest tests pass, node --check and git diff --check pass;
5 CLI commands / 9 HTTP requests pass with evidence equality and state checks.
Inspected 1100x820 and 375x812: no horizontal overflow, full CMI message fits on
desktop, 15px/12px hierarchy verified, first/last suppression evidence and
measurement valid=0/short_record checked, keyboard focus retained. At 100% the
no-footer case remains Unknown; raw missing END remains Incomplete; fatal+exit0
remains Failed. No browser console errors or notification permission requests.
Runtime .runtime/ui-hierarchy-09o5es0n/ contains unittest-final.txt, smoke.json,
dashboard.jpg and mobile.jpg. Existing http://127.0.0.1:55921 viewer reused.
No commit/push performed by this UI task.

## 2026-11-03 — Repository-first onboarding and SSH instructions

User prefers handing another Agent a repository URL and asks how SSH is set up.
Read README.md and plan/v1.md. Verified a cold local clone of committed HEAD
4d18835 in an external path with spaces: Python -S source invocation (no pip or
site-packages) scanned 8 tracked real fixtures with expected states. A link can
exercise these examples; real logs require operator-provided paths/authorization.
No configured Git remote exists and current local fixes/docs remain uncommitted.

Made README/AGENTS repository-first; added docs/agent-quickstart.md, docs/ssh.md
and examples/ssh_config.example. Documented no-install source operation,
remote session lifetime, external SSH profiles, matching-port forwarding and
operator-supplied paths/authorization. Retained the offline ZIP as optional.
No embedded SSH connector, user-profile changes, real server connections,
simulation actions, commit or push.

Local OpenSSH ssh -G -F parsed the template without a host connection. 68 tests
pass; source CLI cold clone and 10 existing-viewer HTTP requests pass. Browser
shows six cases with no console errors; a separate UI task is still editing its
layout. git diff --check passed. Details in docs/validation.md; output in
.runtime/repo-onboarding-lq1rwi7b/. Current uncommitted changes must be published
through the user's normal authorized Git workflow before a shared URL has them.

## 2026-11-03 — Portability and handoff

User asked how to give the tool to another Agent/person and whether delivery is
source CLI, pip or MCP. Read README.md and plan/v1.md. Existing pyproject.toml has
a console entry point and web package data, but an actual offline pip wheel
build failed: implicit discovery found both plan and simcheck. No MCP server or
configured Git remote exists. CLI/pip/MCP are invocation/distribution/integration
choices, not mutually exclusive product forms.

Fixed explicit package ownership; a normal root pip wheel build now succeeds.
Added scripts/package_handoff.py, docs/handoff.md and docs/agent-handoff.md.
The offline ZIP contains the wheel, relocatable synthetic demo, manifest template,
Agent/API/install docs and hashes; source/runtime/private logs are excluded.
There is no PyPI/Git publication, MCP server or bundled Python interpreter.

Validated offline installation in a fresh external venv, commands from an
unrelated working directory, and import origin in installed site-packages.
11 installation/CLI/module checks and 11 installed HTTP requests passed, plus
synthetic append -> wait -> rule/evidence lookup. Inspected the installed page;
no console errors. 68 unittest tests pass; git diff --check passed. Added 3
regressions for relocation and refusing unrecorded/tampered bundle inputs.
Audit output: .runtime/portability-20261103-3535xnja/. Details and untested
platform/real-Spectre boundaries in docs/validation.md. The separate UI task's
English/white-theme source edits remain untouched and are included as the
recorded current application snapshot. Source logs/simulators remain read-only.
Deliverable: dist/spectre-log-inspector-0.4.0-handoff-20261103T070225Z.zip
and its SHA-256 file. Verified application snapshot still matches current code.
Stopped the audit's installed demo viewer (PID 38216) after matching its command
line and DB against the recorded recipient; no other viewer/process touched.
No commit/push.

## 2026-11-03 — English interface and white theme

User requested English throughout the interface and a white main surface.
Read README.md and plan/v1.md before edits. Translated dashboard-owned labels,
statuses, accessible names, tooltips, time labels and browser notifications;
log evidence and user-provided values stay verbatim. Set a fixed light palette,
white body/detail surface and pale sidebar; removed the system-dark override.
Pause updates / Resume updates now explicitly name the existing UI action.
CLI/API/parser behavior unchanged.

Validation: node --check; final full unittest suite 68 tests pass (including
three distribution tests added concurrently by another worker). The existing
unsupported-POST test intermittently failed with Windows 10053; its request
now has an empty body while still checking HTTP 501, with no server changes.
Five CLI commands and nine HTTP requests pass. In-app browser inspected at
1100x820 and 375x812: white computed body/main backgrounds, English labels,
no horizontal overflow; evidence first/last, measurements, details and pause/
resume checked. No parser, source-log or simulation changes. Validation outputs
and dashboard.jpg in .runtime/ui-english-light-hp7xjjkx/; existing viewer reused
at http://127.0.0.1:55921 without a restart. Prior work, concurrent packaging/
handoff files and .claude/ retained. No commit/push.

## 2026-11-03 — Verification audit and synthetic examples

User asked whether the refactors were verified, what evidence is captured, and
for several examples. Read README.md and plan/v1.md before edits. Historical
records describe v0.1/v0.2/v0.3/v0.4 suites of 22/24/52/57 tests; these are records,
not independent proof of every previous worker invocation.

Fresh baseline: 57 tests, 1 error in the foreign-Host HTTP test. A controlled
comparison reproduced a proxy-generated empty HTTP 502 with the default urllib
opener and the expected JSON HTTP 403 with ProxyHandler({}). Changed only the
test HTTP client to explicit direct requests with a 5-second timeout;
server/parser behavior unchanged. Added six hand-authored synthetic cases,
byte hashes/provenance, an example manifest, eight regression tests and
docs/examples.md. Cases cover completion, running warnings/notices/TB issues,
fatal+exit0, missing footer, short raw and wrong-analysis PASS. No private
inputs used; original fixtures untouched.

Final full suite: 65 tests pass. Smoke: 13 CLI calls and 16 HTTP requests pass,
including evidence parity and Host rejection. Inspected dashboard in in-app
browser: states, timeline, evidence expansion, measurements, settings and raw
incompleteness; no page errors. Details/limitations in docs/validation.md.
git diff --check passed; new non-fixture files also checked for whitespace.
Runtime output in .runtime/audit-20261103-kt57edu1/. A read-only static viewer
was started by this task at http://127.0.0.1:55921 (PID 12716); no collector or
simulator is associated with it. Existing .claude/ is untracked and untouched.
Simulation/source logs remain read-only. No commit/push.

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

## 2026-11-02 — v0.4 agent-first output

User: the page still carried redundant text; keep key facts only. More important
is what the executing agent reads: it must not flood the agent's context, and it
must be easy to fetch and locate.

Output builders moved into store (shared by CLI and HTTP), contract API 4: absent
keys mean false/none/zero, times to 6 significant digits, eNNN evidence handles,
one cursor (last evidence ID + state token) for wait. CLI prints compact text by
default (new simcheck/render.py) and the same content with --json; SIMCHECK_DB
replaces repeated --db. Commands: status, wait, show, evidence, measurements,
details; report and problems removed. status lists runs needing attention first
with their first errors in log order, rule hits merged per rule and keys missing
from the baseline; show hides NOTICE groups no rule names; wait returns change
lines and the next command only, a new group that hits a rule as one line.
Every list is bounded. Page rebuilt around key facts only: no captions, legend,
rule/baseline blocks, timestamps or footer; one row per problem group; tabs
problems/measurements/details. Collection, parsing and schema 3 unchanged.

57 tests pass. 8 example logs: status 2368 B text / 3690 B JSON (v0.3 ~17.9 KB),
show noise 2475 B, evidence 454 B, one wait result 209 B. End to end, wait woke
1.26 s after a CMI-2753 line was appended. Details in docs/validation.md. Preview
viewer restarted on the new code (.runtime/preview.sqlite). Committed at the
user's request on branch v0.4-agent-output; main not moved, nothing pushed.
