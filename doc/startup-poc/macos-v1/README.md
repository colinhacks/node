# Node startup proof of concept

This 15-patch V8-based Node fork starts empty programs **1.88–1.89× faster** than its same-revision PGO/ThinLTO control on an Apple M1 Max. That is about 47% less process-lifetime latency, not a 2× same-source improvement or Bun parity.

| Empty program | Control median | Fork median | Paired control/fork ratio, 95% CI |
| --- | ---: | ---: | --- |
| CommonJS | 29.002 ms | 15.329 ms | 1.88929 [1.87688, 1.90650] |
| ES module | 29.308 ms | 15.570 ms | 1.87666 [1.86484, 1.88692] |
| Eval | 29.209 ms | 15.486 ms | 1.88158 [1.86767, 1.89715] |

The [combined report](evidence/current-overall-defensible-clean/report.json.gz) and [raw samples](evidence/current-overall-defensible-clean/raw.jsonl.gz) contain 350 randomized paired rounds, 10 warmups per workload/runtime, 10,850 successful measured samples and no failures. These are warm-cache launch-to-exit measurements, including teardown; ratios are medians of paired ratios, not divisions of the table medians.

- [Patch digest](PATCHES.md): each change, marginal evidence and tradeoffs.
- [Reproduction](REPRODUCE.md): source reconstruction, fresh training, build and measurement commands.
- [Evidence index](evidence/index.json): readable summaries and runtime hashes for all 18 included timing experiments.
- [Manifest](MANIFEST.json): original and published hashes, compression details and redactions.

## Scope

The pinned upstream base is [`8af75451e9041cd6058080ad3d4a65546797b418`](https://github.com/nodejs/node/commit/8af75451e9041cd6058080ad3d4a65546797b418). The [source manifest](patches/manifest.json) records the resulting tree and every changed file; the [ordered diffs](patches/series) permit reconstruction without relying on a moving branch.

- **Build control:** both measured binaries use the same frozen PGO profile. The [control diff](controls/pristine-pgo.patch) adds Darwin PGO/ThinLTO support and preserves executable exports; it contains no runtime startup optimizations. This is not a comparison with an optimally independently trained control.
- **Host:** macOS 26.6.2, arm64, Apple M1 Max, 64 GiB RAM. The recorded build used Apple Clang 21 and SDK 26.5. This effort's builds/tests were idle during timing; unrelated host activity was not controlled.
- **Configuration:** the [audit](evidence/final-config-scope.json) identifies three optional order-file variables and computed whole-program-vtable enablement as the normalized differences. The timing harness consequently labels the comparison exploratory. It is a combined source/build comparison, not an isolated effect of any one patch.
- **Environment:** the final run removes inherited `NODE_*` and `__NUB_*` variables and invokes direct binaries. Historical marginal experiments retain their original environment records; they are not relabeled as clean final-candidate runs.
- **Portability:** all included timings are macOS arm64 measurements. Linux, Windows, debug and pointer-compressed full validation is incomplete; no results for those configurations are claimed here.

## Validation

The [recorded local gate](evidence/local-gate.json) passed the 6,173-case Node selection with 370 skips, 11 TODO-tagged cases and no unexpected failures. Existing Node tests were not modified; this package includes selected gate summaries, not the complete local test logs or a full cross-platform CI result.

The principal compatibility costs are explicit:

- Private executable and bundled-ICU exports are removed. Addons importing undocumented implementation symbols can break.
- Whole-program virtual-call optimization requires public-interface annotations and [bounded build enablement](evidence/wpd-build-policy.json). The [compiler control](evidence/wpd-control/result.json) demonstrates incorrect external dispatch when the boundary is missing.
- Apple framework initialization moves to first use. Loader bindings, system-timezone behavior, certificates and process lifetime remain maintenance obligations.
- PGO and code ordering require training/toolchain provenance. The measured profile, order file and executables are identified by hash but are not shipped as portable binaries or build inputs.

## Evidence handling

Compressed reports retain all numeric fields; compressed JSONL retains every sample, including warmups. The [verifier](tools/verify_evidence.py) checks package hashes and recomputes summaries and paired medians, with optional bootstrap-CI verification.

```sh
python3 doc/startup-poc/tools/verify_evidence.py --bootstrap
```

Local workspace/home paths were replaced with placeholders, private temporary paths were normalized, and free-form JSON notes were omitted. The manifest lists each transformation and preserves source hashes; those hashes identify the original files, not the redacted copies. Historical metadata paths are provenance labels, not downloadable files. No credentials, internal coordination notes, cloud records, binaries or PGO profiles are included.
