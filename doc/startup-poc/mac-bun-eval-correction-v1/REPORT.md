# macOS Bun eval correction

## Scope

This record corrects only the macOS `eval-empty` Bun comparison. The earlier workload passed `-e ''`; Bun 1.3.14 printed help text and exited zero, so its 6.235875 ms median was not a JavaScript no-op measurement. The preserved old files are `artifacts/current-overall-defensible-clean-run/raw.jsonl` (`f6646a4d233ec8cab2e7345a11e47d0b4974590ae0762517701e8f0995927ded`) and `report.json` (`af1374a3d34a40215753812a2431e0258a3350a7b025e1bc1dbe2480f5e02ca1`).

The corrected workload is `-e ';'`. It requires exit code zero and zero stdout. The harness now marks nonempty stdout as `unexpected-stdout`; the regression test uses a successful help-printing runtime and requires that failure. The correction does not refresh any other macOS workload or any Linux or Windows result.

## Measurement

The main run used 10 warmups and 350 interleaved measured rounds with seed `20260927`. It ran the frozen fork `artifacts/node-defensible-v1` (`f7845d078891ed853f9cdc0e7d38f105bd7bec9c7ac9d16a5978f6bc7a469d42`), the specified pristine PGO baseline `artifacts/node-pristine-pgo-use` (`836ec5f8f76b35f46e8c7badd8d4a9e6a03fc6841d85155ffecf6232281f6eb8`), and Bun 1.3.14 at `<HOME>/.bun/bin/bun` (`e0c90ec15d33363e6b70713d56bc3b2c7585c17f40a0fe0f8fd9305901d4e233`). The harness was [`startup_lab.py`](startup_lab.py) (`d4970822336247d49900603000fed72a087e213bbe641b4e715b8df5edf8471c`).

| Run | Measured samples | Fork median | Baseline median | Bun median | Paired ratio, 95% bootstrap CI |
| --- | ---: | ---: | ---: | ---: | --- |
| Main | 350 per runtime, all valid | 14.5036665 ms | 28.1195625 ms | 12.7445205 ms | Fork/Bun 1.14058 [1.13760, 1.14489] |
| Identity control | 350 per runtime, all valid | 14.2342915 ms | 14.2286250 ms | 12.6382080 ms | Same binary baseline/fork 0.99601 [0.99136, 1.00036] |

The main baseline/fork paired ratio was 1.92186 [1.91096, 1.93156]. Its configurations intentionally differ, so the harness records that pair as exploratory rather than patch-attributable. The corrected macOS conclusion is limited to this no-op workload: Bun was 1.14058× faster than the frozen fork, not the invalid 0.40195× figure from help output.

## Evidence

The recorded command is [`driver.sh`](driver.sh). It requires the original local artifacts and path substitutions; this public evidence directory does not contain the executables. The copied build configurations and manifests are in [`configs`](configs). The raw main data and generated report are in [`evidence/main`](evidence/main); the same-binary control is in [`evidence/identity-control`](evidence/identity-control). Public process snapshots before and after the run are [`process-load-before.txt`](process-load-before.txt) and [`process-load-after.txt`](process-load-after.txt). They retain only PID, PPID, CPU, memory, and state; command arguments are omitted. The runner strips `NODE_*` and `__NUB_*` variables and records the removal policy in both generated reports. Public copies replace absolute home prefixes with `<HOME>`. The [sanitization ledger](SANITIZATION.json) records each private input SHA-256 and the public payload SHA-256; gzip evidence also records its public compressed SHA-256. Numeric samples and artifact hashes are unchanged, but public bytes intentionally differ from private evidence.
