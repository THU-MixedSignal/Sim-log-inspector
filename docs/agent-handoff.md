# Agent contract: Spectre Log Inspector 0.4.0 / API 4 / DB schema 4

This is a read-only simulation evidence tool. Never start, stop, pause, modify
or resubmit simulations through this handoff. Never edit source logs, PDKs or ADC
scripts. Report observed facts and rule matches; do not infer circuit causes,
ADC correctness or spectral/spur results. complete does not qualify the circuit.

For a repository-link handoff, first follow docs/agent-quickstart.md at the
repository root. Source invocation needs no pip install. SSH setup and remote
path ownership are in docs/ssh.md; reuse the operator's authorized SSH alias.
In an offline ZIP these repository-only guides are not included; use INSTALL.md.

The operator supplies these values:

- Installed executable path (simcheck, or python -m simcheck in its environment).
- Absolute DB path. Pass --db on every call or set an absolute SIMCHECK_DB.
- Absolute manifest path if collection is needed; source read access and DB write access.
- Whether a collector is already running. Keep one collector per database.

## Start and read

`simcheck --version` should report 0.4.0. Use `--help` for syntax. These commands
use uppercase placeholders; substitute the supplied paths and actual handles.

```text
simcheck --db DB watch MANIFEST --interval 2
simcheck --db DB status --json
simcheck --db DB show RUN --json
simcheck --db DB evidence eID --json
simcheck --db DB measurements RUN --tail 20 --json
simcheck --db DB details RUN --json
```

watch is long-running; the caller must manage its execution session. run adds
HTTP/dashboard to the collector. scan indexes once then exits. Read commands and
serve never refresh sources themselves. If a collector already runs, read that
index. All JSON is UTF-8 and bounded. Read API.md for fields and omission rules.

Inspect existing attention items from status first. Fetch problem groups with
show and original evidence with evidence before making a factual report. Preserve
native severity, time uncertainty, source location and parsing limitations.
Unknown/incomplete is not pass. Running in a sidecar is a reported state, not a
process-liveness probe. reported_valid is a testbench value, not an ADC oracle.

## Wait loop

Save status.cursor, then use a finite wait timeout compatible with the caller:

```text
simcheck --db DB wait --cursor CURSOR --timeout 30 --interval 2 --json
```

- Exit 0: a batch of changes, not simulation success. Process new/status/rule/
  quiet/error/offline changes and fetch evidence as needed.
- Exit 3: timeout; no attention change observed. Continue using the returned cursor.
- Exit 4: no live collector. Data is stale; report/check collection, not simulator health.
- Exit 1/2: tool or argument error; inspect the error, do not interpret it as a run verdict.

Keep each returned cursor and call wait again after handling the batch. If more
is present, use status/show to inspect remaining facts. Default wait ignores
known-group repeats and ordinary new NOTICE groups; --repeats/--notices opt in.
Notices that match watch rules remain NOTICE. Do not invent an error severity.

The host must return stdout/exit status to the Agent. This program does not send
messages into a chat or independently wake a dormant Agent. HTTP is a read-only
JSON query API without a wait endpoint; HTTP callers poll. Browser notifications
are a separate human channel. The page's Pause updates button affects the page.

## Portability

The wheel needs Python 3.10+, no third-party runtime package and no Git checkout.
Keep the virtual environment/runtime DB outside source logs. Use paths on the
machine running the tool. SSH/mounting/credentials are external. HTTP listens on
127.0.0.1 and validates Host; it is not an MCP server. No MCP registration is
provided. Use CLI/JSON or HTTP if the Agent supports them. Re-index moved source
paths into a new DB; do not transfer evidence handles/cursors between databases.
