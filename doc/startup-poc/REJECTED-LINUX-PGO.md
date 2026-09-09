# Native optimized-build results

The first Linux optimized comparison improved empty startup by about **1.44×**, but exposed substantial throughput regressions. That PGO/visibility recipe is **rejected**. The [final Windows comparison](WINDOWS.md) reached **1.139–1.146×** empty-startup speedup without an established regression against the no-LTO baseline in its 14 throughput workloads.

## Linux controls

All five executables use the pinned Node source revision and the same Clang 20.1.8 toolchain on the Ubuntu 24.04 x64 VM. The optimized arms share the same frozen training profile; the source-only baseline does not use PGO or ThinLTO.

| Arm | Source/build change | Executable SHA-256 |
| --- | --- | --- |
| Baseline | Pristine source, no PGO/LTO | `a74cb2a6f3dfec29874838867554b0e27c28ff0d79a520b87e278211963070e0` |
| PGO control | Pristine source, LLVM PGO/ThinLTO | `d2a434d69d80c2c76051fca2012cb64d92e1b6f55c02e373a86a2bb3a48c87de` |
| Fork PGO | Original 15 patches, same PGO/ThinLTO | `863c0b79f8f15d97d0d25164236c0afe2237544a44bc2c200d9533f2de14a720` |
| Entropy | Fork PGO plus the OS-entropy adaptation | `e4db634c846a3d5e9499181b3705dd24797b1b8a9be71d50284cc2ed9a833913` |
| Visibility | Entropy plus optional private ELF C++ symbols | `f5b50bbe6649448ddb83e8239832aefca7c8463b090e183b11de6ea42019168c` |

## Linux startup

The [350-round, 12-workload report](linux-optimized-rejected/evidence/startup/report.json.gz) passed output, exit, timeout and executable-hash checks. Ratios below are medians of paired baseline/candidate latencies; higher is faster.

| Empty program | Baseline median | Visibility median | Baseline / visibility, 95% CI | Equally optimized pristine / visibility, 95% CI |
| --- | ---: | ---: | --- | --- |
| CJS | 22.514 ms | 15.638 ms | 1.43701 [1.42726, 1.45329] | 1.30918 [1.29316, 1.32704] |
| ESM | 23.242 ms | 15.990 ms | 1.44753 [1.43235, 1.46363] | 1.31453 [1.30015, 1.32866] |
| Eval | 23.106 ms | 15.971 ms | 1.44000 [1.42348, 1.45318] | 1.29727 [1.28578, 1.30703] |

The incremental entropy change reduced empty latency by about 1.5–2.4%; visibility added about 0.5–0.8%. Entropy increased the complete first-random task by 3.1% and first-SHA256 by 1.9% relative to the fork PGO arm. All 12 complete tasks were still faster than the source baseline.

The [100-round identity control](linux-optimized-rejected/evidence/identity-control/report.json.gz) found no significant CJS/ESM difference, but its eval ratio was 1.02222 [1.00832, 1.05419]. That is a failed statistical parity control despite a successful harness verdict. Small incremental results require caution.

The separate [350-round first-JavaScript diagnostic](linux-optimized-rejected/evidence/first-js/summary.json.gz) measured baseline/visibility ratios of 1.46063 for CJS, 1.45481 for ESM and 1.44014 for eval. All three inline same-artifact first-JS controls included parity. These are timestamped diagnostic fixtures, not the empty-program measurements above.

The [separate release/reference run](linux-optimized-rejected/evidence/release-references/report.json.gz) measured Bun 1.3.14 at about 11.1 ms for empty files, versus 15.8–16.2 ms for visibility. Node 26.7.0 measured 21.6–22.3 ms. Neither Bun parity nor 2× startup was reached on this Linux host.

## Linux throughput regressions

The [30-round official-benchmark comparison](linux-optimized-rejected/evidence/throughput/report.json.gz) measures in-process operation rates, not launch time. These percentage changes invert the raw paired baseline/candidate rate ratios: positive means more candidate throughput.

| Workload | Visibility vs source baseline | Visibility vs PGO control |
| --- | ---: | ---: |
| Buffer comparison | +6.78% | −0.31% |
| Buffer creation from an array | **−31.84%** | **−32.50%** |
| Bulk SHA-256 | −0.01% | −0.02% |
| Small SHA-256 | +33.23% | −0.69% |
| Random bytes | +34.50% | −0.69% |
| Windows-1252 decoding | **−31.69%** | +17.15% |
| Filesystem read | +6.65% | −1.00% |
| Filesystem stat | +7.00% | −2.36% |
| HTTP parsing | +73.85% | +5.10% |
| Cached module loading | +13.11% | −1.93% |
| Uncached module loading | +15.38% | −1.45% |
| Stream piping | +0.20% | −0.65% |
| Transcoding | −0.57% | +1.15% |
| URL parsing | +30.54% | −0.27% |

These are point estimates, not claims that every row differs significantly. The raw report retains every paired confidence interval and all intermediate arms.

- **Buffer creation:** the pristine PGO control retained approximately 1.09 million operations/s. The original-15 fork PGO arm already fell to 737,000, before the entropy patch. This is not evidence that entropy introduced that particular regression.
- **Decoding:** the pristine PGO recipe alone reduced throughput from approximately 50,300 to 29,400 operations/s. Fork arms recovered to approximately 34,500, still substantially below the source baseline.
- **Disposition:** a [fresh targeted comparison](LINUX-PGO-DIAGNOSIS.md) reproduced both large regressions. The exact shared-profile PGO/visibility recipe is rejected; a favorable address or extra padding is not a production fix. The [final source-only comparison](LINUX-SOURCE.md) does not show those large losses. A separate ThinLTO-only build experiment isolates the linker optimization from PGO before the final Linux recipe is selected.

## Compatibility

| Selection | Baseline | Candidate | Result |
| --- | --- | --- | --- |
| Linux broad suite | 6,142 planned cases | 6,144 planned cases | No unexpected failures in final runs; candidate uses a short project path |
| Linux native C++ | 226 | 233 | Passed |
| Linux precompiled baseline addons under visibility | — | 187 planned cases | Passed |
| Windows corrected broad suite | 6,097 planned cases | 6,099 planned cases | Same eight failures in both; 505 skips and nine TODOs each |
| Windows native C++ | 226 | 233 | Passed |
| Windows normal addon build groups | Five | Five | Passed after LTO-flag isolation fix |
| Windows precompiled baseline addons | 187 planned cases | 187 planned cases | Passed with canonical `node.exe` names; seven skips each |

The [final Linux suite log](validation-v1/linux-pgo-rejected/node-tests.log.gz) includes default, pummel, addon, FFI, Node-API, embedding, benchmark, SQLite and documentation tests. Earlier long-path socket failures reproduced in both control and candidate; an external temporary directory also changed one snapshot's expected path. The final short-project-path run changed neither executable bytes nor existing tests.

The [Windows baseline](validation-v1/windows-baseline/result.json.gz) and [candidate](validation-v1/windows-final/result.json.gz) retain the same DLL-sharing, administrator-filesystem, CRLF snapshot and SQLite command-quoting failures. Two N-API benchmark C fixtures also fail to compile as MSVC C. Matching failures are not a green suite; targeted controls are recorded separately.

The [optimized Windows follow-up](validation-v1/windows-followup/result.json.gz) passed both canonical-name addon checks. All 9,737 baseline PE export tokens remain in the candidate, which adds 15 exports. Dynamic-base, NX and Control Flow Guard indicators remain present. Isolated Clang-CL builds of the two N-API C fixtures produced three positive official CSV rates for each executable; isolated CRLF snapshot fixtures passed both. These controls preserve the original broad-suite failures rather than relabeling them as passes.

Linux ELF checks retained PIE, RELRO, immediate binding and non-executable stack protections. No public Node-API/libuv/module-registration C exports were removed. Private C++ symbols were intentionally removed; the addon check is not an exhaustive C++ ABI or ecosystem proof.

## Coverage limits

Native Windows results are complete in the [Windows report](WINDOWS.md). The isolated Linux ThinLTO experiment is complete in the [Linux final report](LINUX.md): it avoided the large PGO regressions and is retained as an optional throughput/build improvement, not a startup gain. Fork GitHub Actions has not run; these VM gates are not a claim of the full upstream CI matrix.
