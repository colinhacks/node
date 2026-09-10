# Linux final results

This is the frozen 18-patch result. The [renewed 22-patch Linux report](LINUX-RENEWED.md) contains the later source, PGO and ThinLTO comparisons; the measurements below remain unchanged.

The source-only fork reached 1.294–1.302× faster empty startup in the final four-artifact run. Optional ThinLTO reached 1.281–1.296×: it did not improve startup, but improved several throughput workloads without the large regressions of the rejected PGO recipe.

| Artifact | Compiler configuration | SHA-256 |
| --- | --- | --- |
| Pristine source | Clang/LLD, no LTO or PGO | `a74cb2a6f3dfec29874838867554b0e27c28ff0d79a520b87e278211963070e0` |
| Source fork with entropy | Matched no-LTO configuration | `e70434843e822b1d1aa836c627e2d1abcd9191a1419a065fae899e9a0cd40604` |
| Pristine ThinLTO | Same toolchain, ThinLTO only | `d5adf667cac6d21d585b03e65416c93bfe3dd2afbbb62b13246ec2bc58d79233` |
| Final ThinLTO fork | Same ThinLTO configuration | `acac36a74dac6b0cf9b15397c879499b53d23b3e0dcc7f57ae7c44ca556687ea` |

All artifacts use base `8af75451e9041cd6058080ad3d4a65546797b418`. The host was an Intel Ice Lake x64 Ubuntu 24.04 VM with 16 vCPUs and 64 GiB RAM, Clang/LLD 20.1.8, Python 3.12.3 and Rust 1.89.0. Full V8, ICU, OpenSSL, snapshots and Temporal remained enabled. Both configurations used `-g0`; neither used host-specific ISA tuning. The isolated ThinLTO pair used no PGO, whole-program devirtualization or hidden-visibility optimization.

## Startup

The final run used 350 randomized paired rounds for each of 12 workloads. The following table shows warm-cache launch-to-exit medians; speedups are medians of paired ratios, not ratios of the displayed medians.

| Empty program | Pristine, ms | Source fork, ms | ThinLTO fork, ms | Pristine/source speedup [95% CI] | Pristine/ThinLTO speedup [95% CI] |
| --- | ---: | ---: | ---: | ---: | ---: |
| CJS | 23.637 | 18.305 | 18.359 | 1.2937 [1.2838, 1.3053] | 1.2813 [1.2718, 1.2965] |
| ESM | 24.258 | 18.586 | 18.707 | 1.3020 [1.2895, 1.3127] | 1.2874 [1.2792, 1.3032] |
| Eval | 24.124 | 18.588 | 18.701 | 1.2955 [1.2786, 1.3054] | 1.2960 [1.2806, 1.3062] |

ThinLTO increased latency relative to the source fork by 0.39% for CJS, 0.56% for ESM and 0.48% for eval. The CJS interval includes no change; the ESM and eval intervals exclude it. This patch is an optional throughput/build improvement, not a Linux startup gain.

- The earlier [source-only run](LINUX-SOURCE.md) measured 1.305–1.355× on these same source artifacts. Both runs are retained; the higher historical result is not substituted for the final result.
- All three final same-artifact launch controls have 95% intervals containing 1. Their point ratios are 1.0089, 1.0170 and 0.9944 for CJS, ESM and eval.
- The 350-round first-JS diagnostic gives 1.2988× CJS, 1.2922× ESM and 1.2827× eval for the ThinLTO fork versus pristine. All three first-JS identity intervals contain 1. Source-only first-JS speedups are 1.3080×, 1.3049× and 1.3040×.
- Every phase passed its exit/output/hash contracts. Confidence intervals describe this host and run; they do not account for every source of cross-machine variance.

The [raw measurement manifest](linux-final-v1/manifest.json) includes all four artifacts, all 12 launch workloads, first-JS diagnostics, identity controls and release references.

## Steady throughput

The run used 30 randomized paired rounds for 14 official Node benchmark configurations. Values below are percentage rate changes for the final ThinLTO fork; positive means faster. The first column includes the transformed 95% interval.

| Workload | Versus pristine no-LTO, % [95% CI] | Versus source fork, % | Versus pristine ThinLTO, % |
| --- | ---: | ---: | ---: |
| Buffer comparison | +19.77 [9.31, 21.72] | +4.45 | +18.65 |
| Buffer creation | +6.10 [4.56, 8.00] | +1.09 | +8.22 |
| Bulk SHA-256 | −0.01 [−0.10, 0.11] | −0.02 | −0.01 |
| Small SHA-256 | +17.76 [14.34, 20.40] | +20.71 | −0.73 |
| Random bytes | +14.15 [13.34, 15.13] | +13.54 | +0.79 |
| Windows-1252 decoding | −0.52 [−1.47, 0.66] | +0.76 | −1.84 |
| File reading | +0.45 [−4.30, 4.33] | +1.80 | +1.66 |
| File stat | +3.73 [−0.33, 5.14] | +2.62 | −2.30 |
| HTTP parsing | +23.76 [22.11, 24.54] | +23.00 | +0.81 |
| Cached module loading | +0.57 [−0.25, 1.97] | +2.37 | −1.25 |
| Uncached module loading | +3.26 [0.65, 4.26] | +4.04 | −1.05 |
| Stream piping | +0.42 [−0.29, 1.06] | +0.66 | +0.33 |
| Transcoding | +2.22 [1.29, 2.99] | +1.61 | +0.24 |
| URL parsing | +8.03 [−12.95, 9.60] | +8.47 | −2.70 |

No rate regression versus the no-LTO pristine baseline is established by these 14 intervals. This is not a universal no-regression claim. Against equally optimized pristine ThinLTO, decoding (−1.84%), file stat (−2.30%) and cached modules (−1.25%) have intervals excluding parity. URL parsing has a wide interval and is not an established gain.

The source-only fork also has small losses. In this final run, small SHA-256, Windows-1252 decoding and URL parsing have intervals excluding parity against pristine; cached-module uncertainty now includes parity. The earlier source report retains its own decoder/module losses. Compiler choices and binary layout affect these microbenchmarks, so improvements are not attributed to a specific source patch without its own ablation.

The [rejected Linux PGO experiment](REJECTED-LINUX-PGO.md) lost roughly one third of Buffer-creation and decoder throughput. Those losses reproduced in held-out checks. Isolating ThinLTO removed those large losses, so the PGO result is not used to reject ThinLTO or to claim a regression-free PGO build.

## Compatibility

Both ThinLTO builds passed the broad native gate selection without changes to existing tests. The [validation package](validation-linux-final-v1/manifest.json) retains raw TAP, C++ logs, configurations, build manifests and ELF inventories.

| Gate | Pristine ThinLTO | Final ThinLTO |
| --- | ---: | ---: |
| Node test plan | 6,142 | 6,144 |
| Unexpected failures | 0 | 0 |
| Skips / TODOs | 387 / 10 | 387 / 10 |
| Native C++ tests | 226 passed | 233 passed |
| Embedding and addon fixture builds | Passed | Passed |

The selected suites include default, pummel, addons, FFI, JS native API, Node-API, embedding, benchmarks, SQLite and documentation. Earlier long-path socket and external-temp-directory fixture failures are retained separately. The successful runs used short project paths and preserved executable hashes.

Four native GYP configuration cases passed across eight generated Ninja graphs: Node ThinLTO flags are present when enabled, external addons do not inherit them, no-LTO builds omit them, and GCC builds receive no Clang ThinLTO flags. The final Node binary is 139,104,216 bytes versus 145,318,104 bytes for the source baseline, about 4.3% smaller.

ELF checks retain PIE, RELRO, immediate binding and a non-executable stack. All 36,421 global dynamic symbols remain, including the public C and N-API exports. ThinLTO removes 5,951 weak C++ emissions, including inline public V8 defaults; the pristine and final ThinLTO export sets are identical. Weak binding alone is not an ABI guarantee.

The [supplemental validation](validation-linux-supplement-v1/manifest.json) checks those ABI concerns against old binaries:

- The same pristine-built addon fixtures passed the 86-case addon selection and 101-case JS-native/Node-API selection on source pristine, ThinLTO pristine and ThinLTO final. Fixture hashes were unchanged before and after every selection.
- A separate addon was compiled once with pristine headers, Clang 20, `-O0 -fno-inline`, and no LTO. It derives from the public V8 allocator and platform interfaces and uses the inspector defaults. Virtual calls and its N-API control passed under all three executables. The addon supplies its own weak definitions for the removed defaults; no target undefined dynamic reference remains.
- These probes do not establish compatibility for every C++ addon or for programs depending on incidental executable exports. They do establish that the removed V8 defaults used by this probe do not require an out-of-line copy in Node.

The frozen source-only entropy executable also completed a 6,128-case broad JavaScript selection with two fixture failures, 396 skips and 10 TODOs. Its separate basename changed the expected warning hint, and its no-LTO `process.config` did not match the ThinLTO checkout's configuration file. Both failures reproduced with the pristine source executable under the mismatched fixtures. Both tests passed on both unchanged binaries with canonical `node` names and their retained original configurations. The broad run used already-built ThinLTO-checkout addon fixtures and excluded native C++ and embedding binaries; it is not a new all-green, fully matched source-build suite.

## Release references and limits

A separate 200-round run compared the final ThinLTO fork with published Node 26.7.0 and Bun 1.3.14. These are different source versions and build recipes, not attribution controls.

| Empty program | ThinLTO fork, ms | Node release, ms | Bun, ms |
| --- | ---: | ---: | ---: |
| CJS | 18.725 | 22.786 | 11.793 |
| ESM | 18.919 | 23.235 | 11.682 |
| Eval | 19.020 | 23.403 | 11.627 |

Neither 2× same-revision startup nor Bun parity was reached on Linux. These measurements cover one x64 VM and selected warm-cache workloads, not cold boots, Linux arm64, every workload, debug or sanitizer builds, or the addon ecosystem. Fork GitHub Actions has not run.
