# Renewed Linux experiments

The branch adds four commits after the frozen 18-patch package. Linux measurements and cross-platform CI for these additions are still in progress. The earlier [Linux result](LINUX.md) and [Bun comparisons](BUN-COMPARISON.md) describe their original artifacts, not this newer branch. No new 2× or Bun-parity result is established.

## Changes and measured margins

A quiet 220-round Linux x64 screen compared actual binaries against the freshly rebuilt source-fork control. Ratios below are paired control/candidate process-lifetime ratios; higher means faster. The [scalar evidence](linux-renewed/screen-scalars-v1.json) retains confidence intervals and hashes of the full raw reports. These margins cannot be multiplied into a combined result.

| Commit | Change | Screening evidence | Costs and remaining checks |
| --- | --- | --- | --- |
| [19 — Linux LLVM PGO](https://github.com/colinhacks/node/commit/e22d4673456e6dd59f2e246e9b2abd0e38151d5c) | Adds opt-in Clang profile generation/use with explicit profile input, without requiring LTO. | Earlier balanced-recipe binary: CJS 1.0849×, ESM 1.0836×, eval 1.0839×, worker 1.1077×. | Training and extra builds are required. The older build emitted profile-CFG mismatch warnings; those timings are observations, not a provenance-clean PGO result. Exact-source retraining, the full throughput matrix and a pristine PGO control remain pending. |
| [20 — Script-based source positions](https://github.com/colinhacks/node/commit/99d932a15875728562a62d65a2c0499af0d3953b) | Enumerates published scripts and their function lists instead of scanning every heap object when collecting detailed source positions. Retains eligible functions strongly and deduplicates LiveEdit entries. | CJS 1.0277×, ESM 1.0266×, eval 1.0172×, worker 1.0205×. | Must cover streaming, code cache, snapshots and retained old LiveEdit functions. Four focused cases pass with both original and replacement collectors; a deliberate no-op collector fails the three earlier cases. Adds a bundled-static private V8 test target. |
| [21 — Dictionary rehash scratch](https://github.com/colinhacks/node/commit/7efdf3f40841ab7b6ff8dcad2fc8f9ce7c8d42d6) | Copies and reinserts complete snapshot dictionary entries for capacities 32–2048, avoiding repeated in-place displacement. Other capacities retain the original algorithm. | CJS 1.0167×, ESM 1.0138×, eval 1.0254×, worker 1.0216×. Together with commit 20: about 1.039–1.044×. | Up to 64 KiB dynamic scratch plus 1 KiB inline on 64-bit builds. Tests cover counts, holes, values, property metadata and boundaries. The combined decoder screen was about 1% slower; full throughput assessment remains pending. Test integration depends on commit 20. |
| [22 — Deserializer reservation](https://github.com/colinhacks/node/commit/e0ecad7bc3c17754a8f1f522fb089e686e00ad33) | Estimates initial back-reference vector capacity from snapshot payload size, bounded to 2048–32768 entries. Does not alter the snapshot format. | Roughly 0.5–1% startup improvement, with the eval confidence interval including no change in the latest screen. | Extra transient native allocation. The 50-round worker RSS screen measured +0.647%, 95% interval +0.439–0.837%. Full combined throughput and memory checks remain pending. |

## Compatibility evidence

The normal, non-PGO combined-source Linux x64 binary passed:

- 238 native C++ tests, zero failures or disabled tests.
- A 6,144-case release-suite plan: 387 skips, 10 TODO annotations, zero unexpected failures.
- Addon, Node-API, FFI, embedding and SQLite fixture builds, documentation build and the selected documentation tests.

The [gate result](linux-renewed/source-gates-v1.json) records the exact commands and selection. The [artifact identity](linux-renewed/source-artifact-v1.json) pins the executable SHA-256. These are finite release-mode checks, not all upstream configurations or an ecosystem guarantee.

The prior [fork CI run](https://github.com/colinhacks/node/actions/runs/34394590195) completed with all six Linux/macOS jobs green. Windows baseline and candidate passed native tests but failed the same four JavaScript tests: an inaccessible WindowsApps bash alias and three binary-addon loading cases. The shared failures remain disclosed; the run is not green. That run predates these four additions.

## Status

Current-source cross-platform CI, complete combined timing/throughput measurements, the PGO control comparison and final retention decisions remain in progress. No upstream PR, merge or release has been made.
