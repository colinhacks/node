# Native Windows results

The final Windows fork starts empty programs **1.139–1.146× faster** than the same-revision no-LTO baseline. The 14 selected throughput benchmarks found no statistically established regression against that baseline; smaller losses against the equally optimized control are disclosed below.

## Controls and artifacts

All arms use Node revision `8af75451e9041cd6058080ad3d4a65546797b418`, V8, full ICU, snapshots, OpenSSL and Temporal. The native host was Windows Server 2022 x64 on an Ice Lake G Cloud VM, with 16 vCPUs, 64 GiB RAM and Windows Defender real-time protection enabled.

| Arm | Build | Executable SHA-256 |
| --- | --- | --- |
| Baseline | Pristine source, Clang-CL, no LTO | `aef9dd2c2230f4dbc5cad9521a1a3015e01ad40c88c86d1c8ae930164df0f4a3` |
| ThinLTO control | Pristine source, ThinLTO | `5f37a4f3167fbb3bad3da8772c37a3e763cd5513f72464cd18759c1dcea33b69` |
| Fork ThinLTO | Original 15 patches, ThinLTO | `9edf588b41ef8ea6b6191a71958116b3248ce88a5e7592cd20bbc8ddf5a8d758` |
| Final entropy | Fork ThinLTO plus OS startup entropy | `f7555c9a9e130a4766bfe01421e3c31f0fc3de40fbed8fd13d1b938d7ecb5989` |

The toolchain was VS 2022 17.14.37614, MSVC 14.44.35207, Clang-CL/LLD 19.1.5, SDK 10.0.26100, Python 3.14.7, Rust 1.89.0 and NASM 3.01. The final executable is 104,248,832 bytes, versus 115,630,592 bytes for the no-LTO baseline. The [reproduction instructions](REPRODUCE.md) distinguish the ordinary Release configuration from the `release` argument that also enables scoped LTCG.

## Startup

The [startup report](windows-final-v1/evidence/startup/report.json.gz) contains 350 randomized paired rounds across 12 workloads. Ratios are baseline/final latency; higher means faster final startup. Medians include process teardown, not just reaching JavaScript.

| Empty program | Baseline median | Final median | Paired speedup, 95% bootstrap CI |
| --- | ---: | ---: | --- |
| CJS | 68.771 ms | 60.437 ms | 1.14000 [1.13673, 1.14282] |
| ESM | 69.603 ms | 61.191 ms | 1.13912 [1.13598, 1.14273] |
| Eval | 66.500 ms | 58.189 ms | 1.14629 [1.14097, 1.15066] |

- ThinLTO alone reduced pristine empty-start latency by about 1.9–2.0% in this run.
- The entropy addition reduced empty latency by 3.62% CJS, 3.73% ESM and 3.74% eval against the ThinLTO fork. First-random latency increased 0.23% [0.11%, 0.40%]; first-SHA-256 latency decreased 1.67% [1.48%, 1.85%]. These complete tasks include loading and using crypto.
- All three 100-round same-executable startup controls included parity in their confidence intervals.

The separate [first-JavaScript diagnostic](windows-final-v1/evidence/first-js/summary.json.gz) measured 1.13792× CJS, 1.13570× ESM and 1.13816× eval speedups. It uses 350 rounds with an inline same-baseline identity arm; all three identity intervals include parity. These timestamped fixtures are not the empty-program measurements above.

## Steady throughput

The [throughput report](windows-final-v1/evidence/throughput/report.json.gz) records 30 paired rounds and three warmups for each of 14 official Node benchmarks. The table transforms the median paired baseline/final rate ratio into a final-throughput percentage; positive means more throughput. Confidence bounds are inverted in the opposite order.

| Workload | Final vs no-LTO baseline | 95% interval | Final vs ThinLTO control |
| --- | ---: | ---: | ---: |
| Buffer comparison | +2.56% | [+2.40, +3.70]% | +1.49% |
| Buffer creation from an array | +0.84% | [+0.38, +1.48]% | +25.80% |
| Bulk SHA-256 | +0.04% | [−0.01, +0.09]% | +0.04% |
| Small SHA-256 | +2.17% | [−1.19, +7.55]% | −1.73% |
| Random bytes | +12.97% | [+12.01, +13.39]% | −0.48% |
| Windows-1252 decoding | +0.20% | [−1.36, +1.54]% | +0.32% |
| Filesystem read | +0.18% | [−1.36, +1.73]% | −1.39% |
| Filesystem stat | +1.33% | [+1.15, +1.84]% | +0.73% |
| HTTP parsing | +16.44% | [+14.26, +18.70]% | +1.03% |
| Cached module loading | +1.65% | [+0.95, +2.68]% | −0.50% |
| Uncached module loading | +2.22% | [+1.40, +3.19]% | −1.14% |
| Stream piping | +1.57% | [−1.00, +3.91]% | −0.89% |
| Transcoding | +5.27% | [+4.22, +6.76]% | approximately 0% |
| URL parsing | +3.36% | [+2.71, +4.07]% | +0.14% |

The optimized-control column is not uniformly positive. Random-byte and uncached-module throughput losses against that control have confidence intervals excluding parity; the report retains every interval and intermediate arm.

The large Buffer difference is an artifact-level result, not an entropy-algorithm claim. The pristine ThinLTO and original-15 ThinLTO binaries fell from roughly 564,000 to 452,000–454,000 operations/s; the final entropy binary reached 568,000. Startup entropy does not run inside this benchmark's hot loop. Related Linux experiments demonstrated code-placement sensitivity; this Windows run does not establish the cause or guarantee that another build retains the same layout.

## Compatibility

The [baseline](validation-v1/windows-baseline/result.json.gz) and [final candidate](validation-v1/windows-final/result.json.gz) ran the same broad native selection.

| Gate | Baseline | Final |
| --- | ---: | ---: |
| Planned JavaScript cases | 6,097 | 6,099 |
| Skipped cases | 505 | 505 |
| TODO-tagged cases | 9 | 9 |
| Unexpected failures | 8 | 8 |
| Native C++ tests passed | 226 | 233 |
| Pristine-addon cases under canonical executable name | 187, seven skips | 187, seven skips |

The same eight failures occurred in both builds: three DLL-sharing cases, three administrator-filesystem/ACL cases, the CRLF-sensitive TypeScript snapshot fixture and the SQLite extension command-newline case. This is **not a fully green suite**. Existing Node tests were not modified.

The [targeted follow-up](validation-v1/windows-followup/result.json.gz) passed canonical-name loading of pristine-built addons and CRLF snapshot fixtures on both binaries. Two N-API benchmark fixtures rejected as MSVC C compiled with Clang-CL and produced three valid official benchmark rates for each binary. These controls do not erase the broad-suite failures.

Patch 17 prevents private Node LTO flags from leaking into external MSVC addon compilation. Five normal addon build groups passed after the change on both optimized builds. Node's own full/thin/non-LTO compiler graphs were unchanged. All 9,737 baseline PE export tokens remain in the final binary, with 15 additions; dynamic-base, NX and Control Flow Guard indicators remain present. This is not exhaustive ABI or hardening certification.

## Release references and limits

The [200-round reference comparison](windows-final-v1/evidence/release-references/report.json.gz) used released Node 26.7.0 and Bun 1.3.14. These are version/build references, not same-source controls.

| Empty program | Final fork | Released Node | Bun |
| --- | ---: | ---: | ---: |
| CJS | 62.362 ms | 68.957 ms | 74.946 ms |
| ESM | 63.088 ms | 69.897 ms | 74.788 ms |
| No-op eval | 60.108 ms | 66.820 ms | 73.465 ms |

The fork was faster than Bun in this Windows VM run, but did not approach a 2× improvement over Node's same-source baseline. This is not a general cross-platform Node-versus-Bun result. A single bounded process/file observation ran during the reference phase to check the VM's approaching shutdown deadline; the primary startup, throughput and first-JS phases had already finished.

All five phase contracts passed, with unchanged executable hashes. The [public-safe package](windows-final-v1/manifest.json) retains compressed reports and every raw sample; its verifier recomputes 444 summary checks. The retrieved archive SHA-256 is `8f76b9282838c4d5776ef75256ec8e415b18e50374e8ebdd82f1e5d9560a5296`. The owned Windows VM and auto-delete boot disk were removed after retrieval; the Linux experiment continues separately.

Fork GitHub Actions has not run. These results cover this native x64 release configuration, not debug builds, sanitizers, Windows ARM64, configured FIPS, the full addon ecosystem or the complete upstream CI fleet.
