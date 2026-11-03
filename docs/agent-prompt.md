# Copyable Agent onboarding prompt

Replace the connection/path placeholders with operator-provided values. These
are handoff notes, not fields recognized by the application. Share no private
key, passphrase or token in this prompt. A private repository requires GitHub
read access on the receiving machine. Pin the commit supplied by the sender if
reproducibility is needed; otherwise record the cloned HEAD.

```text
Repository: https://github.com/chenzc24/spectre-log-inspector
Revision: <sender-supplied commit, or record the cloned HEAD>

Clone into a separate writable workspace. Read AGENTS.md, README.md,
docs/agent-quickstart.md and docs/agent-handoff.md before using the tool.
Python 3.10+ is required. From the repository directory use python -m simcheck
(python3 on Linux); pip installation is optional. First run --version, then
scan examples/real-fixtures.json into a new .runtime/onboarding.sqlite with
--json. Expected: a_fft/b_fft/noise/static complete, and minstep/compile/
output_limit/license failed. No simulator is launched by this self-check.

For the actual remote task, use only this authorized configuration:
SSH alias: <existing alias in this machine's user .ssh/config>
Remote repository/work directory: <absolute path>
Remote manifest/log paths: <absolute paths>
Remote derived database: <absolute path in a writable monitoring directory>
Existing collector: <yes/no; if yes, read its DB and do not start another>

SSH is external OpenSSH. Reuse the existing alias/key or ssh-agent; host,
user, port, identity path and optional ProxyJump stay in local .ssh/config.
The operator must have verified the server host key and authorized login.
Do not put credentials in Git, the manifest or chat, disable host-key checking,
or guess missing hosts/paths. Ask for any required missing configuration.

Keep the collector and SQLite on the log server. Use server-side log paths
in the manifest. Maintain one run/watch collector per DB in a managed command
session; a disconnected SSH shell may end that monitoring session. Query
status -> wait --cursor -> show -> evidence using --json. Use finite wait
timeouts, preserve each returned cursor and distinguish exit 0/3/4. The
program does not independently wake a dormant Agent.

If the remote viewer uses 8765, forward only loopback:
ssh -N -T -o ExitOnForwardFailure=yes -L 127.0.0.1:8765:127.0.0.1:8765 SSH_ALIAS
Use equal local/remote ports for the application's Host validation. Check
/api/health and collector.live, not just whether a tunnel exists.

Report original severity, text, location, uncertainty and user-rule matches.
Never launch, stop, pause, modify or resubmit a simulation; never edit source
logs, PDKs or ADC scripts. unknown/incomplete/offline is not pass. complete
does not qualify electrical performance or ADC codes. No circuit-cause or
spectral/spur analysis. See docs/ssh.md for detailed setup and boundaries.
```
