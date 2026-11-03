# SSH configuration and remote observation

SSH is provided by the connecting machine's OpenSSH client. Spectre Log
Inspector does not open SSH connections, save credentials, edit .ssh/config,
install keys or manage remote jobs. It reads file paths local to its collector.
An ssh:// log path or piping ssh tail -f into simcheck is not an input mode.

## Separate three configurations

| Configuration | Owner/location | Contents |
|---|---|---|
| Repository URL/revision | Git client on each machine fetching source | Source code access; Git authentication if private |
| SSH connection | Connecting user's ~/.ssh/config (Windows: user profile .ssh/config) | Alias, hostname, user, port, identity, optional jump host |
| Run manifest + DB path | Machine hosting the collector | Existing local log/sidecar paths, analysis/watch rules; writable derived DB |

Git repository access and access to the simulation server are independent. An
Agent may be able to clone source and still lack permission to read remote logs.
Supply a known authorized host alias, the remote repo/work directory, log paths
and intended database. Repository links alone cannot supply these values.

## Reuse an authorized SSH profile

Prefer an alias already provided by the operator, for example spectre-box.
examples/ssh_config.example shows the supported OpenSSH configuration shape;
it is an example, not a real host to contact. If a profile is needed, the operator
configures actual host/user/port and an already-authorized identity in their
local .ssh/config. Private keys/passphrases stay outside this repository and
outside chat; OpenSSH may use an existing local key or ssh-agent. With
IdentitiesOnly yes, IdentityFile must identify the intended key. ProxyJump is
optional and refers to a separately configured, authorized bastion alias.

StrictHostKeyChecking yes requires an already-trusted known_hosts entry. The
operator verifies first-contact fingerprints through a trusted channel. Do not
disable host checking or auto-trust an unverified key. BatchMode yes makes an
Agent invocation fail rather than hang on password/passphrase interaction; an
operator must resolve interactive authentication before unattended use.

These checks are separate:

```sh
ssh -G spectre-box
ssh -o BatchMode=yes -o ConnectTimeout=10 spectre-box python3 --version
```

The first prints the effective local configuration without connecting. The
second checks authorized login and remote Python, not log permissions or
simulation health. Keep configuration output local. This repository never
connects to the sample hostname during tests or configures the user's profile.

## Keep collection and the database on the server

After the operator provides authorized access and a monitoring workspace,
clone the repository on that server and follow agent-quickstart.md. Keep this
workspace separate from ADC scripts, PDKs and source logs. In an SSH shell,
from the remote repository directory, start the monitoring tool:

```text
python3 -m simcheck --db ABSOLUTE_REMOTE_DB run ABSOLUTE_REMOTE_MANIFEST --port 8765 --interval 2
```

The uppercase paths are placeholders. The manifest's paths are server paths,
not paths on the connecting laptop. Use one collector per DB; if one already
exists, query it instead. The invoking SSH/Agent session must remain alive unless
the operator has independently arranged persistence. This app does not install
services, daemonize, reconnect SSH or resume a closed remote session. SSH loss
does not stop the independent simulation, but this collector session may end.

For an Agent that needs one-shot remote queries, an optional pip installation
on the server allows an absolute executable path without depending on a shell's
working directory. For example, after that environment has been installed:

```sh
ssh -T spectre-box /home/sim_reader/tools/spectre-log-inspector/.venv/bin/simcheck --db /local/simcheck-work/index.sqlite status --json
```

Use an operator-confirmed local disk for the SQLite WAL database. The writer rejects known network mount types on Linux and remote drives on Windows. Other layouts require checking the mount. Source logs can live on the shared filesystem. Paths/user are illustrative; substitute operator-provided values. wait, show
and evidence use the same form. Keep wait timeouts within the calling tool's
timeout and save returned cursors. If invoking source directly, set the remote
repository working directory for that invocation.

## Forward the dashboard/API to a local machine

With the server listening on its loopback port 8765, run locally:

```sh
ssh -N -T -o ExitOnForwardFailure=yes -L 127.0.0.1:8765:127.0.0.1:8765 spectre-box
```

Open http://127.0.0.1:8765 locally. The local end is explicitly loopback-only;
the server remains bound to its own 127.0.0.1. Use equal local/remote ports:
the application validates the Host header against the server's bound port, so
local 18765 -> remote 8765 receives HTTP 403 with a normal browser. If 8765 is
occupied, choose another free port at both ends and for the remote tool.
ExitOnForwardFailure reports initial tunnel binding failures; it does not prove
the HTTP application is healthy. Check /api/health and collector.live as well.

Only HTTP/CLI results cross SSH in this setup; the collector reads increments
of the server's log files and writes its SQLite locally. HTTP has query endpoints
but no wait endpoint; a local Agent using HTTP polls it. A remote CLI wait can
block for bounded changes and return JSON over SSH. MCP is not involved.

## Alternative: externally mounted logs

An operator may provide a read-only remote filesystem mount visible locally.
Then the local manifest points at mounted paths and the DB stays on the local
disk. Mounting/authentication are external; caches and disconnects affect when
new log bytes become visible. Copying logs once provides a snapshot, not live
observation. Do not place a shared live SQLite WAL DB on the log mount.

## Verification boundary and references

Current automated/installation checks are on Windows/Python 3.13. The SSH template
can be parsed locally with ssh -G -F without contacting any host. A real server,
Linux runtime, keys, bastion, forwarding policy and full live observation chain
still need validation on the actual authorized environment. No real SSH or
simulation action is implied by these examples.

OpenSSH reference: [ssh_config](https://man.openbsd.org/ssh_config) and
[ssh](https://man.openbsd.org/ssh).
