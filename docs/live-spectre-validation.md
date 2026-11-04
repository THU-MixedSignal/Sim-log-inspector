# Native Spectre validation

On November 3, 2026, the inspector replayed **16 managed Spectre runs**. Fourteen came from the initial campaign. The syntax-error and wall-timeout cases finished later. The replay used the original output and a fresh schema 4 index based on commit `96c8b33`. The sanitized fixtures, source run IDs and SHA-256 hashes are in [the fixture directory](../tests/fixtures/live_20261103/).

The campaign used Spectre 21.1.0.509.isr12. Isolated tests used Spectre X CX with one thread. The ADC tests used MX with four threads. Across the original 14 runs, the maximum observed RSS was about 370.48 MiB. The collector retrieved 217,472 bytes of small evidence files and one 54,470-byte ASCII RC result. ADC waveform files stayed on the server.

## Observed results

| Run | Simulator or launcher evidence | Inspector result |
| --- | --- | --- |
| `rc-normal` | Exit 0, transient PASS, zero errors | Complete. The ASCII raw has an END marker and reaches 20 ns. |
| `syntax` | SFE-874, exit 2 | Failed. The original diagnostic identifies the input line. |
| `model-missing` | SFE-23, exit 2 | Failed. The missing model or subcircuit is identifiable. |
| `param-missing` | SFE-1997, exit 2 | Failed. Preserves the parameter error and continuation. |
| `include-missing` | SFE-868, exit 2 | Failed. Preserves the file-read error. |
| `ahdl-compile` | VACOMP-2212/1647, exit 2 | Failed. Preserves the Verilog-A compiler messages. |
| `topology` | Rigid branch loop, exit 2 | Failed. Captures the unnumbered FATAL. |
| `dc-nonconv` | SPECTRE-16080, exit 1 | Failed before transient analysis began. |
| `tran-minstep` | SPECTRE-16927 at 5.00081 ns, exit 1 | Failed at 25.0% progress. The unnumbered Newton NOTICE retains its severity and can trigger a rule. |
| `soa` | 1.2 V against a 0.99 V limit, five printed occurrences each of CMI-2751 through CMI-2755, then suppression, exit 0 | Complete with SOA issues. Preserves signed values, suppression and the missing IC timestamp. |
| `tb-records` | Four R4MEAS lines, one FAIL and one PASS | Three parsed frames and three other testbench records. Invalid, short and FAIL records remain distinguishable. |
| `output-limit` | 1 MiB cap, SPECTRE-27/7082, FATAL, exit 0 | Failed. The launcher reports an output limit. |
| `wall-limit` | Intended 8-second timeout, reached the 8 MiB cap after about 3.10 s | Failed on the output cap. Wall-time coverage comes from the following case. |
| `wall-nooutput` | 6-second wall limit, elapsed 6.1538 s, SPECTRE-25, exit 2 | Failed. Preserves the launcher's `wall_time_limit` reason. |
| `adc-a-tt` | 0.9 V, 27 °C, 359 ns, exit 0 | Complete. Three valid frames with codes 231, 44 and 183. No CMI group. |
| `adc-b-tt` | Same external conditions and three codes, five CMI groups, exit 0 | Complete. The five additional CMI groups remain visible against A. |

The A/B DUT, surrounding testbench, standard-cell includes and observer matched the frozen FFT run by SHA-256. The top-level stop time changed from 103259 ns to 359 ns. The reports distinguish the requested `gear2only` method from the effective `trap` setting. These three frames establish short-run agreement only.

## Replay and regression checks

- SHA-256 matched for 42 original log, state and logStatus files against the collected copies. The fresh index held 406 events. Scanning again did not duplicate them. First and last occurrences, header lines and continuations matched the source.
- A queued run can have a managed state before its log exists. A completed state without its required log remains incomplete. An expected stop time only requires raw evidence when the manifest configures a raw file.
- A solver diagnostic mentioning zero elapsed time no longer resets progress within the same analysis. Testbench FAIL/PASS and R4MEAS lines with native progress prefixes retain their classifications. The earliest rule hit keeps its own timestamp, including when none was logged.
- A rapid same-size rewrite with identical metadata could leave stale log or state evidence. Regression tests force identical metadata, verify that changed contents invalidate the cache, and check that stable large files use metadata only. Sampling the ends of a large file cannot detect every silent rewrite in its middle.
- A local replay held back a partial SOA line. Once the line was complete, the agent received the warning after about 0.217 s. This measures local collection latency. When the collector stopped, `wait` returned exit code 4.
- The CLI, HTTP API and Edge dashboard were checked against the 16 runs. Evidence expansion and measurement loading worked for all six testbench records and the three ADC frames. Controlled copies with truncated RC output or an incorrect analysis name reported incomplete.

The initial live capture used an external SSH adapter that mirrored at most 64 KiB per log per read. Simulation inputs, PDKs and shared libraries stayed read-only. Only the single-thread RC test used a temporary CPU-gate exception. The original policy was restored and its SHA-256 verified. The campaign did not induce host-wide OOM, exhausted storage, swap failure or a shared-license outage. Other Spectre versions and binary PSF remain outside this campaign.

For a local replay, run `python -m unittest discover -s tests -p test_live_spectre.py -v` from the repository root. The tests use the committed fixtures and do not require Spectre or a license.
