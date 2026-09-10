# Bun comparison

This report replaces the canonical direct-comparison table with the corrected macOS no-op eval and the renewed Linux result. It measures warm-cache process lifetime, including teardown. Each platform uses its own host, artifact, and fixtures; it is not an operating-system ranking.

## Results

The paired ratio is `Bun / fork`; below one means Bun was faster. Ratios are paired statistics, not divisions of the displayed medians.

| Platform | Workload | Fork median, ms | Bun median, ms | Bun / fork paired ratio [95% CI] |
| --- | --- | ---: | ---: | ---: |
| macOS arm64 | Empty CJS | 15.328958 | 13.653562 | 0.893350 [0.888526, 0.899648] |
| macOS arm64 | Empty ESM | 15.570376 | 13.570084 | 0.866928 [0.862014, 0.874379] |
| macOS arm64 | No-op eval | 14.503666 | 12.744521 | 0.876749 [0.873447, 0.879040] |
| macOS arm64 | Hello | 17.393313 | 20.236458 | 1.166063 [1.156140, 1.172318] |
| macOS arm64 | Built-ins | 17.749876 | 23.112437 | 1.303327 [1.295988, 1.313376] |
| macOS arm64 | First crypto use | 18.514146 | 19.087667 | 1.036169 [1.028836, 1.043923] |
| macOS arm64 | HTTP ready | 21.554708 | 28.266625 | 1.300543 [1.293026, 1.309300] |
| Linux x64 | Empty CJS | 14.808267 | 11.091880 | 0.751291 [0.745642, 0.753868] |
| Linux x64 | Empty ESM | 15.234730 | 11.057375 | 0.724477 [0.719910, 0.732384] |
| Linux x64 | No-op eval | 15.096225 | 10.911538 | 0.720856 [0.718433, 0.727623] |
| Linux x64 | Hello | 18.135290 | 10.925391 | 0.602979 [0.599415, 0.606116] |
| Windows x64 | Empty CJS | 62.361900 | 74.946400 | 1.201995 [1.197988, 1.205270] |
| Windows x64 | Empty ESM | 63.088050 | 74.787900 | 1.186058 [1.182752, 1.189299] |
| Windows x64 | No-op eval | 60.108100 | 73.465100 | 1.221008 [1.219602, 1.224593] |
| Windows x64 | Hello | 63.013450 | 73.963300 | 1.174700 [1.170774, 1.176828] |

## macOS eval erratum

The archived macOS `-e ''` row is invalid. Bun 1.3.14 printed help text and exited zero, so its 6.235875 ms result was not JavaScript execution. The replacement runs the frozen same 15-patch artifact with `-e ';'`, exit code zero, and empty stdout. It changes no other macOS row and does not measure the later entropy artifact. See the [macOS correction evidence](mac-bun-eval-correction-v1/REPORT.md).

## Linux renewal

Linux now uses the selected `combined-thin-pgo` artifact from the renewed final matrix. The release-reference raw data records 200 valid measured samples per runtime and workload. The prior Linux rows remain available as [archived Linux v1](LINUX.md); this document does not combine their figures with the renewed run.

## Measurement provenance

| Platform | Host | Report | Fork artifact SHA-256 | Bun SHA-256 |
| --- | --- | --- | --- | --- |
| macOS arm64 | Apple M1 Max, macOS 26.6.2, 64 GiB | [350 eval rounds](mac-bun-eval-correction-v1/evidence/main/report.json.gz); [earlier non-eval rows](macos-v1/evidence/current-overall-defensible-clean/report.json.gz) | `f7845d078891ed853f9cdc0e7d38f105bd7bec9c7ac9d16a5978f6bc7a469d42` | `e0c90ec15d33363e6b70713d56bc3b2c7585c17f40a0fe0f8fd9305901d4e233` |
| Linux x64 | Intel Ice Lake, Ubuntu 24.04 G Cloud VM, 16 vCPUs, 64 GiB | [200 rounds](linux-renewed/final-v1/release-references/report.json.gz) | `ffa49c64dc7ecc307c58252a4c38b5159b9a68c9d0c60247af609ca0c53b0ed0` | `9fd36f87e4b90b07632b987a2e4ec81ca15a62c81bf983190cea6d715be2ad74` |
| Windows x64 | Windows Server 2022 Ice Lake G Cloud VM, 16 vCPUs, 64 GiB | [200 rounds](windows-final-v1/evidence/release-references/report.json.gz) | `f7555c9a9e130a4766bfe01421e3c31f0fc3de40fbed8fd13d1b938d7ecb5989` | `0187f68d843f825a72ada4a7eca60db896ed753759a7f8252edcd31ac1bf1b9c` |

All direct comparisons use Bun 1.3.14. The frozen macOS and Windows values retain their prior artifacts. Linux uses `combined-thin-pgo` (`ffa49c64dc7ecc307c58252a4c38b5159b9a68c9d0c60247af609ca0c53b0ed0`).

## Same-source controls

| Platform | Result | Boundary |
| --- | --- | --- |
| macOS arm64 | 1.877–1.889x launch-to-exit with the frozen artifact | The corrected no-op eval reports Bun versus that frozen artifact. The 1.92186x baseline/fork configuration pair is exploratory, and the 1.962–1.973x first-JavaScript fixture was not refreshed. |
| Linux x64 | 1.38–1.40x for the same-configuration normal source result; 1.52–1.55x for the source + PGO + ThinLTO recipe versus normal pristine | No pristine ThinLTO + PGO control was measured. |
| Windows x64 | 1.139–1.146x with the retained artifact | The four direct-comparison rows remain from the frozen Windows report. |

## Scope

These selected warm-cache launch and tiny-program workloads do not establish universal runtime performance, cold-start behavior, throughput or compatibility parity, other architectures, or debug, sanitizer, FIPS, and addon behavior.
