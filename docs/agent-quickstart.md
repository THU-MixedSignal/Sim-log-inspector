# Start from a repository URL

This is the default handoff for an Agent with shell access. An offline ZIP and a
pip installation are optional. Read AGENTS.md before operating or changing code.

## Inputs and prerequisites

The target machine needs Git, Python 3.10+ with the standard sqlite3 module, and
read access to the intended Git repository/revision. No third-party Python
runtime dependency, pip install, Spectre binary or simulator licence is needed
for source invocation. Use python/py -3 on Windows or python3 on Linux/macOS.

A repository URL is sufficient to exercise the included sanitized log examples.
It cannot provide authorization or locate a user's real logs. For a real task,
the operator must supply the log paths (or a manifest), writable monitoring work
directory, and whether a collector already exists. For a remote task, also
obtain the authorized SSH alias and the paths on that server; see ssh.md.

## Clone and establish the baseline

The source repository is https://github.com/chenzc24/spectre-log-inspector.
Private repositories require read access on the receiving machine; GitHub access
and simulation-server SSH access are independent. Clone into a new writable
directory; do not overlay an unrelated ADC workspace. If the operator
supplies a tag/commit, check it out and record it. The commands below use python;
substitute the Python command available on that machine.

```sh
git clone https://github.com/chenzc24/spectre-log-inspector.git spectre-log-inspector
cd spectre-log-inspector
git rev-parse HEAD
python --version
python -m simcheck --version
python -m simcheck --db .runtime/onboarding.sqlite scan examples/real-fixtures.json --json
```

The current application version is 0.5.0 (API 4, DB schema 4). Expected states:
a_fft/b_fft/noise/static complete; minstep/compile/output_limit/license failed.
scan exits 0 when indexing/querying succeeds, including when a simulated run
failed. Check the returned states rather than treating the command exit as a
simulation verdict. These are historical fixtures; no simulation is launched.

The source entry point must run with the repository as the working directory.
Set that directory on each Agent shell call; a previous call's cd may not persist.
For convenient invocation elsewhere, an optional venv + pip install . provides
the simcheck command. Source installation needs setuptools build tooling and
may need package-index access. Source invocation above does not need it.

## Observe an existing real run

Create a project-specific manifest in a writable monitoring directory. Start
with required id/log fields; include existing optional state/logStatus/raw only
when the operator intends them to be checked. A minimal manifest is:

```json
{"runs":[{"id":"my-run","log":"/absolute/path/to/existing/spectre.out"}]}
```

On Windows use an appropriate Windows path. Relative source paths resolve from
the manifest directory. Choose an absolute DB path outside the source-log/PDK
directory. The commands below use placeholders:

```text
python -m simcheck --db DB watch MANIFEST --interval 2
python -m simcheck --db DB status --json
python -m simcheck --db DB wait --cursor CURSOR --timeout 30 --json
python -m simcheck --db DB show RUN --json
python -m simcheck --db DB evidence eID --json
```

Keep one collector (watch/run) per database. The caller manages the long-running
command session. With an existing collector, read its DB instead of starting a
duplicate. run adds the local dashboard; --port 0 selects an available port and
--open opens a browser on the machine running the command. serve only reads DB.

Use agent-handoff.md for the status -> wait -> show -> evidence loop and exit
codes. Only the collector updates the index. Missing logs, inaccessible paths,
unknown/incomplete results or an offline collector are not passing evidence.
Do not start, stop, pause, modify or resubmit a simulation.

## What a shared URL guarantees

A clone contains committed files reachable at that URL/revision, not the sender's
uncommitted fixes, ignored runtime DBs, private logs or local SSH configuration.
The sender must publish the intended revision through its normal authorized
Git workflow before another machine can fetch it. This project never commits or
pushes automatically. Validate the exact shared URL/revision on its target OS;
the local cold-clone check is not a test of a remote host or its authentication.
