# Spectre Log Inspector

Spectre Log Inspector reads Spectre logs as they grow. The dashboard shows which runs need attention, where a problem first appeared, and the original lines behind it. Agents can query the same evidence through the CLI or local HTTP API. The inspector reads simulation outputs and writes a separate SQLite index. Simulation scheduling and electrical acceptance remain with the operator.

**Release v0.5.0** requires Python 3.10 or later with the standard `sqlite3` module. The runtime has no third-party dependencies. This release uses API 4 and database schema 4.

## Try it with the included logs

Clone the tagged release from an account with read access to the private repository. The example runs use sanitized logs and require neither Spectre nor a simulator license. On Linux or macOS, use `python3` if that is how Python is installed.

```sh
git clone --branch v0.5.0 https://github.com/chenzc24/spectre-log-inspector.git
cd spectre-log-inspector
python -m simcheck --version
python -m simcheck --db .runtime/demo.sqlite scan examples/real-fixtures.json --json
python -m simcheck --db .runtime/demo.sqlite run examples/real-fixtures.json --open
```

`scan` indexes once and exits. In this example, four runs complete and four fail. Finding failures is the expected result. `run` starts the collector and dashboard together in the foreground. The default URL is [localhost on port 8765](http://127.0.0.1:8765/). Use `--port 0` to choose a free port. Ctrl+C stops the inspector. Windows users can also launch the demo with `Start-Viewer.cmd`.

## Read the dashboard

| Area | What to look for |
| --- | --- |
| Run list | Runs needing attention appear first. Text labels such as **Warning 2** count distinct problem groups. Selecting a run opens its timeline and details. |
| Problems | Read the severity word beside each diagnostic code. Expand a row to see original log text, source path and line number. For repeated problems, switch between the first and last recorded occurrence. Notices without rule hits are folded. |
| Measurements | The table initially shows the latest 50 testbench records. Use **Earlier** for older records or **View** for source evidence. Frame, code and validity come from the testbench. |
| Details | Compare the native footer with any configured managed state, `logStatus`, and raw-output checks. Requested and effective simulator settings appear separately. |
| Collector and timeline | The collector indicator tells you whether the data is updating. The timeline shows logged simulation time. A Spectre progress meter may give a later estimate. **Pause updates** pauses the page refresh while collection continues. |

**Download or close a run from the left sidebar.** The selected row shows two controls. Other rows reveal them on hover or keyboard focus. On narrow screens, the same controls sit beside the run selector. Download offers a self-contained HTML report or a JSON snapshot. Close hides that generation from this browser's list. **Restore closed** brings hidden runs back, and a new generation appears automatically.

**Copy a full report from the run header.** The copy icon works from any tab. It copies a plain-text report for the selected generation, including problem groups, integrity checks, settings, coverage limitations and every indexed event, even those beyond the current measurement page. Downloads and copies contain collected evidence. Source log files and waveform files stay on the simulation host.

## Monitor a project

Keep one directory per run. Give each run a unique ID and a path to its Spectre log. Relative paths resolve from the manifest file. Add sidecars when the corresponding evidence exists. For example, save the following as `manifest.json` beside a `runs` directory.

```json
{
  "quiet_after_s": 1800,
  "watch": [
    {"name": "Operating-limit warning", "code": "CMI-275*"},
    {"name": "Invalid testbench record", "key": "TB:reported_valid=0"}
  ],
  "runs": [{
    "id": "adc-tt",
    "log": "runs/adc-tt/spectre.out",
    "state": "runs/adc-tt/simulation.state.json",
    "analysis": "tran_perf",
    "log_status": "runs/adc-tt/raw/logStatus",
    "raw": "runs/adc-tt/raw/tran_perf.tran.tran",
    "expected_stop_s": 3.59e-7
  }]
}
```

Only `id` and `log` are required. Specify a `baseline` by the ID of another run in the same manifest to identify additional problem keys. Watch rules can filter by code or key pattern, severity, text and minimum count. For a farm with one subdirectory per run, a `roots` entry can discover runs automatically. [Manifest and evidence fields](docs/schema.md)

```sh
python -m simcheck --db .runtime/project.sqlite run manifest.json --open
```

For server jobs, run the collector where it can read the configured paths. Keep its database on local disk and run one collector per database. To separate collection from viewing, use two terminals on that host. Forward the viewer port through an authorized SSH connection for local browser access. [SSH setup](docs/ssh.md)

```sh
python -m simcheck --db .runtime/project.sqlite watch manifest.json
python -m simcheck --db .runtime/project.sqlite serve --port 8765
```

A one-time scan can also be viewed with `serve`. Its collector indicator will correctly report offline. When rebuilding an index, choose a fresh database path, scan the original sources and get a new cursor from `status`. Replacing or truncating a log starts a new generation. Earlier evidence retains its original path, line number and stored text.

## Query from an agent

```sh
python -m simcheck --db .runtime/demo.sqlite status --json
python -m simcheck --db .runtime/demo.sqlite show minstep
python -m simcheck --db .runtime/demo.sqlite measurements noise --tail 20
python -m simcheck --db .runtime/demo.sqlite details noise
```

1. Read `status` for the runs needing attention and a cursor. Use `show RUN` for grouped diagnostics and their evidence IDs.
2. Pass an ID from that database to `evidence ID` to retrieve the original lines. A suppressed count measures printed occurrences. A missing timestamp remains unknown.
3. With a collector running, call `wait --cursor CURSOR` using the actual cursor from `status`. Save the returned cursor for the next wait. Exit code 0 indicates a change, 3 a timeout, and 4 an offline collector. Use `--repeats` or `--notices` when those events should wake the caller.

Set `SIMCHECK_DB` to avoid repeating the database path. Commands return compact text by default and support `--json`. The localhost viewer exposes `/api/status`, `/api/show`, `/api/evidence`, `/api/measurements`, `/api/details`, and `/api/health`. To download a report, request `/api/export?run=RUN&format=html`, using `json` or `txt` for the other formats. [Agent contract](docs/agent-handoff.md) · [New-machine quickstart](docs/agent-quickstart.md) · [Copyable handoff prompt](docs/agent-prompt.md)

## Interpret the evidence

- **Complete** describes execution and the configured output checks. A completed run can still have operating-limit warnings, invalid codes or circuit performance outside specification.
- A FATAL or managed resource-limit failure remains visible even when the simulator exits with code zero. Missing required output is reported as incomplete. A quiet log reports how long it has remained unchanged.
- Simulation timestamps come from the relevant Spectre block. DC and AC sweep coordinates remain sweep coordinates. The raw integrity check samples the head and tail of supported ASCII PSF output.
- Measurements count successfully parsed frames separately from other testbench records. The testbench's reported validity is preserved as recorded.

## Verify the installation

```sh
python -m unittest discover -s tests -v
```

The repository includes eight historical sanitized logs, six synthetic cases, and a 16-run native Spectre campaign covering numerical failures, resource limits, operating-limit warnings, testbench records, and two short ADC runs. See the [native validation report](docs/live-spectre-validation.md), [sample descriptions](docs/examples.md), and [performance validation](docs/validation.md). For a machine without Git access, build an offline wheel and handoff bundle with `python scripts/package_handoff.py`. [Offline installation](docs/handoff.md)
