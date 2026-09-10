# Node startup proof of concept

This V8-based Node fork reduces startup work without bypassing normal program execution. The same-revision comparisons have not reached a 2× startup speedup.

| Platform and build | Empty-startup speedup | Evidence |
| --- | ---: | --- |
| macOS arm64, original 15-patch optimized fork | 1.877–1.889× | [Frozen Mac report](macos-v1/README.md) |
| macOS arm64, subsequent entropy addition | 3.3–3.8% less latency than the frozen fork | [Separate entropy validation](MACOS-ENTROPY.md) |
| Linux x64, current source-only fork, matched normal builds | 1.381–1.395× | [Renewed Linux report](LINUX-RENEWED.md) |
| Linux x64, current fork PGO versus separately trained pristine PGO | 1.387–1.454× | [Renewed Linux report](LINUX-RENEWED.md) |
| Linux x64, current source + PGO + ThinLTO versus pristine normal | 1.519–1.548× | [Renewed Linux report](LINUX-RENEWED.md) |
| Windows x64, ThinLTO fork with entropy | 1.139–1.146× | [Native Windows report](WINDOWS.md) |

The ranges cover empty CJS, ESM and eval programs. These are warm-cache launch-to-exit measurements with interleaved controls on each host. The full Linux recipe changes both source and compiler configuration; it is not a source-only comparison. Margins from different runs cannot be added or multiplied.

- [Patch digest](PATCHES.md): what each of the 22 diffs does, measured margins and compatibility costs.
- [Source commits](COMMITS.md): the independently reviewable commit sequence corresponding to those diffs.
- [Bun comparisons](BUN-COMPARISON.md): the last direct macOS, Linux and Windows measurements, with metric and artifact limits.
- [Completed fork CI](CI.md): six Linux/macOS jobs passed; both Windows jobs failed the same four tests.
- [Current Linux reproduction](linux-renewed/final-v1/REPRODUCE.md) and [frozen platform reproduction](REPRODUCE.md): source reconstruction, build commands and measurement tools.
- [Windows results](WINDOWS.md): startup, first-JS, 14 throughput workloads and compatibility gates.
- [Current Linux results](LINUX-RENEWED.md), [frozen 18-patch results](LINUX.md), [earlier source results](LINUX-SOURCE.md) and [rejected PGO experiment](REJECTED-LINUX-PGO.md): distinct recipes and controls.
- [Frozen Mac package](macos-v1/README.md): original measurements, controls, reproduction and per-patch evidence.

## Compatibility and tradeoffs

The fork retains V8, ICU, OpenSSL, snapshots, workers and normal CLI modes. Existing Node tests were not removed or edited; new regression tests are additive. Finite tests do not establish universal compatibility.

- **Windows:** the broad runs had the same eight failures in both control and candidate, not a fully green suite. Native C++ tests and targeted baseline-addon loading passed. The measured final artifact showed no established throughput regression against the no-LTO baseline in 14 workloads; some small losses remain against the equally optimized control.
- **Linux:** all three current combined builds passed their 6,144-case release plans and 238 native tests. The selected ThinLTO PGO recipe had no established rate regression versus pristine normal in 14 workloads. Non-LTO fork PGO retains roughly 1–2% losses in three workloads versus separately trained pristine PGO. The old PGO/visibility recipe with large Buffer/decoder losses remains rejected; it is not the new balanced recipe.
- **macOS:** the original broad release selection passed. The later entropy change passed native and focused crypto/worker tests; an initial filesystem-read slowdown did not clearly replicate in a separate controlled run.
- **Disclosed behavior changes:** Darwin builds remove private executable/ICU exports; addons using undocumented symbols can break. An invalid OpenSSL DRBG configuration now may fail on first crypto use rather than aborting startup. Very small secure heaps can produce worker-local crypto errors rather than an eager process abort.
- **Maintenance:** profile-guided builds and trained ordering require toolchain/training provenance. Whole-program virtual-call optimization requires maintained public-interface annotations and remains narrowly enabled.

The pinned base is `8af75451e9041cd6058080ad3d4a65546797b418`. The [current 22-patch manifest](linux-renewed/final-v1/source-package/manifest.json) and [frozen 18-patch manifest](patches/manifest.json) record prerequisites, source reconstruction and file identities. Platform-specific options are not blanket defaults.

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
python3 linux-renewed/final-v1/reproduction/verify_manifest.py
```

Frozen native verification recomputes raw coverage, failure counts, medians and paired ratios; it preserves, but does not independently recompute, reported bootstrap intervals. The renewed Linux package adds [raw validation and an independent bootstrap audit](LINUX-RENEWED.md). Selected earlier logs remain in [validation evidence](validation-v1/manifest.json), [frozen Linux validation](validation-linux-final-v1/manifest.json) and [entropy/provider probes](entropy-validation-v1/manifest.json).

The current Linux package includes the measured training profile, build configurations, logs, raw samples and owned-resource cleanup records. Executables and large private archives remain local. Home paths are redacted and public process-load snapshots omit command arguments; credentials are not included.

The nested Mac package preserves the historical measurements, patches and tools. One documentation link was adjusted for nesting and recorded in its manifest; the original export remains retained locally. Its original command examples assumed installation at `doc/startup-poc`; use the nested verifier command above in this combined package. Mac marginal measurements are not Linux or Windows attribution.

The old Mac Bun empty-eval row timed Bun's help output and is invalid. The [corrected comparison](mac-bun-eval-correction-v1/REPORT.md) reruns only eval with the same frozen 15-patch artifact and `-e ';'`, requiring empty stdout. Other Mac rows are unchanged; no newer Mac artifact is represented as measured against Bun.

The [completed fork CI run](CI.md) passed all six Linux/macOS jobs. Both Windows jobs passed native testing and failed the same four JavaScript tests; the run is not green. Source, tests and workflow match the tested head. These gates are separate from VM performance and do not establish debug, sanitizer, all-architecture, configured-FIPS or ecosystem compatibility.
