# Bun comparison

This report collects the last direct comparisons against Bun 1.3.14 on each native host. Each row measures warm-cache process lifetime, including teardown; the macOS artifact predates the later entropy addition.

The table reports the paired `Bun / fork` latency ratio and its 95% bootstrap interval. Below one means Bun was faster; above one means the fork was faster. Ratios are paired statistics, not divisions of the displayed medians.

## Results

| Platform | Workload | Fork median, ms | Bun median, ms | Bun / fork paired ratio [95% CI] |
| --- | --- | ---: | ---: | ---: |
| macOS arm64 | Empty CJS | 15.329 | 13.654 | 0.893 [0.889, 0.900] |
| macOS arm64 | Empty ESM | 15.570 | 13.570 | 0.867 [0.862, 0.874] |
| macOS arm64 | No-op eval | 15.486 | 6.236 | 0.402 [0.399, 0.404] |
| macOS arm64 | Hello | 17.393 | 20.236 | 1.166 [1.156, 1.172] |
| macOS arm64 | Built-ins | 17.750 | 23.112 | 1.303 [1.296, 1.313] |
| macOS arm64 | First crypto use | 18.514 | 19.088 | 1.036 [1.029, 1.044] |
| macOS arm64 | HTTP ready | 21.555 | 28.267 | 1.300 [1.293, 1.309] |
| Linux x64 | Empty CJS | 18.725 | 11.793 | 0.625 [0.620, 0.634] |
| Linux x64 | Empty ESM | 18.919 | 11.682 | 0.614 [0.610, 0.620] |
| Linux x64 | No-op eval | 19.020 | 11.627 | 0.611 [0.608, 0.619] |
| Linux x64 | Hello | 22.886 | 11.512 | 0.504 [0.500, 0.506] |
| Windows x64 | Empty CJS | 62.362 | 74.946 | 1.202 [1.198, 1.205] |
| Windows x64 | Empty ESM | 63.088 | 74.788 | 1.186 [1.183, 1.189] |
| Windows x64 | No-op eval | 60.108 | 73.465 | 1.221 [1.220, 1.225] |
| Windows x64 | Hello | 63.013 | 73.963 | 1.175 [1.171, 1.177] |

The macOS-only extra workloads use the same 350-round report. Bun has no measured worker row because the fixture was Node-only. None of these comparisons measures steady throughput or establishes compatibility parity.

| Workload | Invocation and work |
| --- | --- |
| Empty CJS/ESM | An empty file with the corresponding module extension. |
| No-op eval | macOS uses `-e ''`; Linux and Windows use `-e ';'`. |
| Hello | macOS runs a CJS file that writes `hello` and a readiness marker; Linux and Windows use `-e "console.log('hello')"`. |
| Built-ins | Loads Node-compatible assert/path/URL modules, performs a path assertion, and writes a readiness marker. |
| First crypto use | Loads Node-compatible crypto, hashes a short string with SHA-256, and writes a readiness marker. |
| HTTP ready | Opens and closes a Node-compatible HTTP server on loopback, writing a marker after listen. The row measures through process exit, not just the marker and not request throughput. |

Within each platform both runtimes execute the same fixture. Hardware, operating systems and some fixtures differ across platforms, so absolute times should not be compared across hosts.

## Measurement provenance

| Platform | Host and report | Rounds | Fork artifact SHA-256 | Bun SHA-256 |
| --- | --- | ---: | --- | --- |
| macOS arm64 | Apple M1 Max, macOS 26.6.2, 64 GiB; [report](macos-v1/evidence/current-overall-defensible-clean/report.json.gz) | 350 | `f7845d078891ed853f9cdc0e7d38f105bd7bec9c7ac9d16a5978f6bc7a469d42` | `e0c90ec15d33363e6b70713d56bc3b2c7585c17f40a0fe0f8fd9305901d4e233` |
| Linux x64 | Intel Ice Lake Ubuntu 24.04 G Cloud VM, 16 vCPUs, 64 GiB; [report](linux-final-v1/evidence/release-references/report.json.gz) | 200 | `acac36a74dac6b0cf9b15397c879499b53d23b3e0dcc7f57ae7c44ca556687ea` | `9fd36f87e4b90b07632b987a2e4ec81ca15a62c81bf983190cea6d715be2ad74` |
| Windows x64 | Windows Server 2022 Ice Lake G Cloud VM, 16 vCPUs, 64 GiB; [report](windows-final-v1/evidence/release-references/report.json.gz) | 200 | `f7555c9a9e130a4766bfe01421e3c31f0fc3de40fbed8fd13d1b938d7ecb5989` | `0187f68d843f825a72ada4a7eca60db896ed753759a7f8252edcd31ac1bf1b9c` |

All three reports record Bun 1.3.14. The macOS report records revision `1.3.14+0d9b296af`; the Linux and Windows reference reports identify the release in their platform reports ([Linux](LINUX.md), [Windows](WINDOWS.md)). The reference binaries had matching hashes before and after their runs.

## Same-source controls

The comparison above is a release reference, not the causal control. The same-revision baseline/fork results use the pinned Node base `8af75451e9041cd6058080ad3d4a65546797b418` and matched configurations on each host.

| Platform | Final same-source empty-startup result | Interpretation |
| --- | --- | --- |
| macOS arm64 | 1.877–1.889x launch-to-exit | The frozen 15-patch artifact. A separate timestamp fixture measured 1.962–1.973x to first JavaScript. Installed Node 26.7.0 gave 2.06–2.08x ratios, but is a different release/build and is not a same-source result. |
| Linux x64 | 1.281–1.296x final ThinLTO; 1.294–1.302x source-only | ThinLTO is not a startup improvement over the source fork: 0.39–0.56% slower. Its retention is based on selected throughput/build value. |
| Windows x64 | 1.139–1.146x final entropy artifact | The Windows reference favors the fork on this VM, but it does not show a 2x same-source improvement. |

The later macOS entropy artifact has no direct Bun comparison. Its 3.3–3.8% latency reduction against the frozen fork was measured in a different run, so it must not be combined with the frozen artifact's Bun margin. The earlier Linux source-only result of about 1.30x and the final ThinLTO result of about 1.29x are separate controls, not a route to 2x.

## Scope

These results cover selected warm-cache launch and tiny-program workloads on one host per platform. They do not establish universal Node-versus-Bun performance, cold-start behavior, throughput parity, compatibility parity, other architectures, debug/sanitizer/FIPS configurations, or addon-ecosystem behavior. The platform reports retain the build controls, compatibility gates, and workload definitions: [macOS](macos-v1/README.md), [Linux](LINUX.md), and [Windows](WINDOWS.md).
