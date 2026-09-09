# Node startup proof of concept

This V8-based Node fork reduces startup work without bypassing normal program execution. The same-revision comparisons have not reached a 2× startup speedup.

| Platform and build | Empty-startup speedup | Evidence |
| --- | ---: | --- |
| macOS arm64, original 15-patch optimized fork | 1.877–1.889× | [Frozen Mac report](macos-v1/README.md) |
| macOS arm64, subsequent entropy addition | 3.3–3.8% less latency than the frozen fork | [Separate entropy validation](MACOS-ENTROPY.md) |
| Linux x64, source-only fork with entropy, final run | 1.294–1.302× | [Linux final report](LINUX.md) |
| Linux x64, optional ThinLTO fork | 1.281–1.296× | [Linux final report](LINUX.md) |
| Windows x64, ThinLTO fork with entropy | 1.139–1.146× | [Native Windows report](WINDOWS.md) |

The ranges cover empty CJS, ESM and eval programs. These are warm-cache launch-to-exit measurements; each platform used interleaved controls on the same host. Margins from different runs cannot be added or multiplied. The earlier Linux source-only run measured 1.305–1.355× and remains available separately.

- [Patch digest](PATCHES.md): what each of the 18 diffs does, measured margins and compatibility costs.
- [Source commits](COMMITS.md): the independently reviewable commit sequence corresponding to those diffs.
- [Bun comparisons](BUN-COMPARISON.md): the last direct macOS, Linux and Windows measurements, with metric and artifact limits.
- [Reproduction](REPRODUCE.md): pinned source reconstruction, build commands and measurement tools.
- [Windows results](WINDOWS.md): startup, first-JS, 14 throughput workloads and compatibility gates.
- [Linux final results](LINUX.md), [earlier source results](LINUX-SOURCE.md) and [rejected PGO experiment](REJECTED-LINUX-PGO.md): compiler choices, controls and regressions retained separately.
- [Frozen Mac package](macos-v1/README.md): original measurements, controls, reproduction and per-patch evidence.

## Compatibility and tradeoffs

The fork retains V8, ICU, OpenSSL, snapshots, workers and normal CLI modes. Existing Node tests were not removed or edited; new regression tests are additive. Finite tests do not establish universal compatibility.

- **Windows:** the broad runs had the same eight failures in both control and candidate, not a fully green suite. Native C++ tests and targeted baseline-addon loading passed. The measured final artifact showed no established throughput regression against the no-LTO baseline in 14 workloads; some small losses remain against the equally optimized control.
- **Linux:** both ThinLTO broad suites passed. Optional ThinLTO improved throughput, not startup; no regression against the no-LTO pristine baseline was established in 14 measured workloads. Small losses remain against the equally optimized control. The source-only artifact also has small workload-specific losses. A PGO/visibility build lost roughly one third of throughput in two workloads and was rejected.
- **macOS:** the original broad release selection passed. The later entropy change passed native and focused crypto/worker tests; an initial filesystem-read slowdown did not clearly replicate in a separate controlled run.
- **Disclosed behavior changes:** Darwin builds remove private executable/ICU exports; addons using undocumented symbols can break. An invalid OpenSSL DRBG configuration now may fail on first crypto use rather than aborting startup. Very small secure heaps can produce worker-local crypto errors rather than an eager process abort.
- **Maintenance:** profile-guided builds and trained ordering require toolchain/training provenance. Whole-program virtual-call optimization requires maintained public-interface annotations and remains narrowly enabled.

The pinned base is `8af75451e9041cd6058080ad3d4a65546797b418`. The [patch manifest](patches/manifest.json) records all changed-file hashes, prerequisites and the reconstructed source tree. Platform-specific options are not blanket defaults.

## Verification

Each native evidence directory contains compressed reports, all selected raw samples, original hashes and a sanitization manifest. Run from this directory:

```sh
python3 -B tools/verify_bundle.py verify --package .
python3 tools/verify_native_evidence.py verify --package windows-final-v1
python3 tools/verify_native_evidence.py verify --package linux-source-v1
python3 tools/verify_native_evidence.py verify --package linux-final-v1
python3 tools/verify_native_evidence.py verify --package macos-entropy-v1
python3 tools/verify_native_evidence.py verify --package linux-optimized-rejected
python3 tools/verify_native_evidence.py verify --package linux-pgo-followup-v1
python3 macos-v1/tools/verify_evidence.py --bootstrap
```

Native verification recomputes raw coverage, failure counts, medians and paired ratios; it preserves, but does not independently recompute, the reported bootstrap intervals. Selected native test logs and configurations are in [earlier validation evidence](validation-v1/manifest.json), [Linux final validation](validation-linux-final-v1/manifest.json) and [entropy/provider probes](entropy-validation-v1/manifest.json). Local home/host paths are redacted; binaries, credentials, cloud metadata and private training profiles are not included.

The nested Mac package preserves the historical measurements, patches and tools. One documentation link was adjusted for nesting and recorded in its manifest; the original export remains retained locally. Its original command examples assumed installation at `doc/startup-poc`; use the nested verifier command above in this combined package. Mac marginal measurements are not Linux or Windows attribution.

Fork GitHub Actions results are separate from these frozen VM/local measurements. The [fork validation workflow](https://github.com/colinhacks/node/actions/workflows/fork-startup-ci.yml) runs paired pristine/candidate release builds; its live status is not a performance result. These gates are not the full upstream CI fleet and do not establish debug, sanitizer, all-architecture, configured-FIPS or ecosystem compatibility.
