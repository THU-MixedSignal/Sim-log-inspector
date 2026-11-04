# Install and hand off Spectre Log Inspector 0.5.1

For an Agent that can access the Git repository, the default is to clone and
follow docs/agent-quickstart.md from the repository root; no ZIP or pip install
is required for source invocation. Remote setup is in docs/ssh.md. The rest of
this guide is the optional offline-wheel workflow.

The handoff ZIP contains a Python wheel, this guide, AGENT.md, API.md, a manifest
template, and six small synthetic examples with provenance. It contains no real
simulation logs, databases, runtime state or credentials. BUILD.json records the
application snapshot hashes; FILES.sha256 lists the payload hashes. The separate
ZIP SHA-256 checks transfer integrity; it is not an authenticity signature.

## Windows: install and open the demo

Unzip into a writable folder. In PowerShell, change into the extracted folder
containing the wheel and INSTALL.md, then run:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-index --no-deps .\spectre_log_inspector-0.5.1-py3-none-any.whl
.\.venv\Scripts\simcheck.exe --version
.\.venv\Scripts\simcheck.exe --db .\work\demo.sqlite run .\demo\manifest.json --port 0 --open
```

No Git, repository checkout, Spectre installation or simulator licence is needed
to read the supplied examples. Python 3.10+ with venv/pip is required. Installing
this wheel needs no network or third-party runtime packages. Python itself is
not bundled. Keep the Python process running while monitoring; Ctrl-C stops only
this tool. The demo is a frozen synthetic snapshot, not a live simulation.

## Linux/macOS: command form (not yet platform-validated)

From the extracted folder:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --no-index --no-deps ./spectre_log_inspector-0.5.1-py3-none-any.whl
.venv/bin/simcheck --db ./work/demo.sqlite run ./demo/manifest.json --port 0
```

Open the printed loopback URL on that machine. On a remote server, keep the
collector and database there; use external SSH port forwarding to reach HTTP.
Use matching local/remote ports because the current Host validation checks the
server port. Neither SSH nor credentials are managed by this application.
The pure-Python wheel tag is not evidence of Linux/macOS testing; current actual
validation is Windows/Python 3.13. The app has no MCP server or standalone EXE.

## Point at your own existing simulation

Copy manifest.template.json to a project folder and edit runs[].id and log.
Log paths resolve relative to the manifest, not the current shell folder.
Add state/log_status/analysis/raw/expected_stop_s only for existing sources you
want checked. log_status requires the intended analysis. raw supports only a
bounded PSF ASCII header/tail check, not complete waveform validation.

Use the installed simcheck command with explicit absolute paths:

```text
simcheck --db ABSOLUTE_DB run ABSOLUTE_MANIFEST --port 0 --open
simcheck --db ABSOLUTE_DB status --json
```

ABSOLUTE_DB and ABSOLUTE_MANIFEST are placeholders. Once installed, simcheck
works outside the extracted folder; the executable is inside the virtual
environment's Scripts/ or bin/ directory unless the environment is activated.
The database folder must be writable. Source logs need read access only. For
each database, keep one collector (run/watch) and any number of read clients.
serve/status/wait do not collect logs themselves. CLI --help lists all commands.

## Give the tool to another Agent

Give it AGENT.md plus the installed executable path, absolute database path and
absolute manifest path. If a collector already runs, tell it which database to
read; it should not start a duplicate collector. API.md describes the JSON.
An Agent with shell access can use CLI/JSON immediately. An Agent with HTTP tools
can poll the loopback API or an external SSH tunnel. MCP-only clients require a
future adapter; HTTP JSON alone is not MCP.

## Move to another machine or update the application

Install the wheel into a fresh environment, make the desired logs readable on
the target machine, update the manifest paths and re-index into a new database.
Persisted database source paths are absolute; copying a database does not rewrite
those paths. Evidence handles/cursors belong to a particular database. Do not
reuse them against a newly built index. With unchanged paths on the same host,
an Agent can read the existing compatible index. Old database schemas are
rejected without migration; retain the old file and choose a new database path.

Use a project-owned work directory or an absolute SIMCHECK_DB value; the default
.runtime path is relative to the caller's current directory. Program files,
private inputs and derived runtime data should remain separate. User-provided
watch rules report matches only. complete is an observed completion state, not
an electrical/code verdict; absent/incomplete evidence must not become a pass.

## Source and build workflow

Developers may copy/unzip/clone the repository and run `python -m pip install .`
or `python -m pip install -e .`. That source install needs its setuptools build
dependency; the recipient wheel install above does not. Source is hosted at
https://github.com/THU-MixedSignal/Sim-log-inspector. There is no public PyPI release;
do not assume a package-index project with this name is this artifact.

With Python/pip and setuptools>=68 already available, run from the source tree:

```sh
python scripts/package_handoff.py
```

This builds offline and writes a ZIP plus SHA-256 under ignored dist/. It builds
only the application and web assets from a frozen copy, validates the wheel's
entry point/assets/dependencies, then adds only hash-verified synthetic inputs.
It never uploads, commits or pushes. Building a wheel alone is not verification:
install into a fresh environment outside the repository and check CLI, HTTP,
dashboard and the supplied example states before delivering it.
