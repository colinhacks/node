# macOS entropy validation

This report records the isolated macOS validation of the generic entropy runtime patch. It does not replace the frozen macOS startup artifact or its measurements.

## Inputs

- Source copy: `worktrees/mac-entropy-validation`
- Runtime patch: `startup-lab/platform/entropy/fork-15patch-runtime.patch`
- Additive regression: `startup-lab/platform/entropy/additive-tests/entropy-startup-tests.patch`
- Frozen probe control: `node/out/Release/node`
- Frozen timing comparison: `artifacts/node-defensible-v1`

## Results

The isolated build produced an arm64 Mach-O executable with SHA-256 `811dbd176e7e6df339502d7960480ba9480cdf72ce534f5a2fb5577e8303e1fe`. Its `config.gypi` hash was `c1d4dc1e42bb24a3c74622acbb075bc55ebbcbf9e29f4bfbe8e6912adb64a901`, which matches the frozen fork configuration. The copied source and output files have distinct inodes from the frozen source.

- The full `cctest` executable passed 235 tests in 3.111 seconds.
- The additive startup regression and its five crypto/worker selections passed.
- The existing no-algorithm, secure-heap, and legacy-provider selections passed.
- The entropy probe passed its strict differential contract on macOS with a 15-second process timeout and 500 `randomBytes` throughput iterations.
- The frozen original failed the additive regression as required. Its missing-DRBG child aborted at the eager `ncrypto::CSPRNG(nullptr, 0)` check before JavaScript ran.

The candidate preserved default and legacy-provider crypto. It retained the base-only-provider `SIGABRT` contract. With an unavailable DRBG, it reached JavaScript and failed at first crypto use with `unable to fetch drbg`, while the frozen original aborted at startup. Its secure-heap worker process exited normally, with worker-local secure-malloc errors allowed by the regression contract.

## Benchmark outcome

The shared runner refused macOS before any sample with `paired_bench supports native Windows or native Linux only`. That failed invocation is retained at `artifacts/mac-entropy-validation-v1/paired-bench-macos.result`. The macOS port in `paired_bench_darwin.py` is a copy with only an explicit `sys.platform == "darwin"` host acceptance branch and an updated message. Its source hash is `f6c5f8c99490abc155fc44bae531d1ac4ef31f56343389942fc76bd8caba776e`; the shared runner hash is `f44aea00740a6c50749792a8a5c2f677a06c2fe9865170dde316927e042ecef2`.

The port passed direct POSIX timeout, nonzero-exit, exact-output, process-group containment, and monotonic-clock checks. A three-workload Darwin preflight passed before the declared measurements. All report verdicts passed with unchanged post-run executable hashes.

| Measurement | Rounds | Raw records | Result |
| --- | ---: | ---: | --- |
| Startup | 350 + 10 warmups | 12,960 | 12 workloads and three artifacts |
| Startup identity | 100 + 10 warmups | 660 | Candidate compared with itself on the three empty workloads |
| Throughput | 30 + 3 warmups | 1,386 | 14 workloads and three artifacts |
| Throughput identity | 30 + 3 warmups | 924 | Candidate compared with itself on all 14 workloads |

The startup artifact set was the new candidate, frozen fork (`f7845d078891ed853f9cdc0e7d38f105bd7bec9c7ac9d16a5978f6bc7a469d42`), and pristine PGO control (`836ec5f8f76b35f46e8c7badd8d4a9e6a03fc6841d85155ffecf6232281f6eb8`). The three empty startup ratios for candidate over frozen fork were 0.9619 (95% CI 0.9549–0.9692) for CommonJS, 0.9667 (0.9612–0.9717) for ESM, and 0.9675 (0.9585–0.9744) for eval. The corresponding candidate-over-pristine ratios were 0.5323, 0.5323, and 0.5293. Lower is faster for startup.

The startup same-artifact intervals all included one: CommonJS 0.9783–1.0124, ESM 0.9891–1.0108, and eval 0.9783–1.0102. Throughput reports all passed. The candidate-over-frozen `fs-read` ratio was 0.9197 (0.8522–0.9884), but the candidate same-artifact control for that workload was 1.0593 (0.9549–1.1883). This isolated throughput result is not sufficient to attribute an `fs-read` regression to the entropy patch. The full per-workload medians and bootstrap intervals are in `artifacts/mac-entropy-validation-v1/measurement-summary.json` and the immutable raw records.

## Targeted `fs-read` follow-up

The targeted run used the same official `fs-read` workload for 60 measured rounds and five warmups. Each round interleaved four labels: `entropy-a` and `entropy-b` named the new candidate; `frozen-a` and `frozen-b` named the frozen timing comparison. All 260 raw records passed and the post-run hashes matched their inputs.

The two candidate-versus-frozen primary ratios were 0.9996 (95% CI 0.9139–1.0464) and 0.9686 (0.9124–1.0152). The candidate identity ratio was 0.9998 (0.9618–1.0837). The frozen identity ratio was 1.0052 (0.9605–1.1051). Every interval includes one, so the earlier 30-round `fs-read` observation did not replicate as a clear entropy-patch regression. The host load before and after, configuration, raw records, report, and summary are retained in `artifacts/mac-entropy-validation-v1/fs-read-interleaved-60/`.

## Limits

The patch is validated only with the recorded macOS arm64 PGO, ThinLTO, bounded-WPD, and Darwin-order configuration. The local binary has no configured FIPS provider, so the probe covers only the normal `--enable-fips` startup error rather than configured-FIPS behavior. This work does not establish Linux, Windows, configured FIPS, or full-CI portability.
