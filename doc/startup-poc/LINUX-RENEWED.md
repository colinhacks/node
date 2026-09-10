# Renewed Linux startup results

The selected Linux build starts **1.52–1.55× faster** on empty entries than the normal pristine build. This is the combined source, PGO and ThinLTO recipe, not a same-configuration source-only result; 2× and Bun parity remain unmet.

| Direct paired comparison | Empty CJS | Empty ESM | Empty eval |
| --- | ---: | ---: | ---: |
| New source / pristine, both normal builds | 1.3894× | 1.3813× | 1.3954× |
| Source fork PGO / pristine PGO | 1.3998× | 1.3871× | 1.4535× |
| Source + PGO + ThinLTO / normal pristine | 1.5274× | 1.5195× | 1.5482× |
| Three new V8 changes / frozen source, both normal | 1.0541× | 1.0538× | 1.0579× |
| PGO / normal, same combined source | 1.0926× | 1.0903× | 1.0933× |
| ThinLTO PGO / PGO, same source and profile | 1.0089× | 1.0042× | 1.0059× |

Each row is measured directly. The margins must not be multiplied. PGO controls use the same training recipe with separately generated profiles. No pristine ThinLTO PGO artifact was measured.

## Full measurements

The [generated tables](linux-renewed/final-v1/TABLES.md) contain all six variants, all workloads and 95% bootstrap intervals. The [machine-readable results](linux-renewed/final-v1/RESULTS.json) retain source-report hashes and raw-sample validation.

- Startup: 12 workloads, 350 paired rounds and 10 warmups; 25,920 process launches.
- Throughput: 14 official Node benchmark configurations, 30 paired rounds and three warmups; 2,772 launches.
- References: all six variants, Node 26.7.0 and Bun 1.3.14; four common workloads, 200 rounds and 10 warmups.
- First JavaScript: 350 rounds of CJS, ESM and eval, plus a same-binary control and a deliberate 25 ms busy-wait control. Selected full-recipe speedups were 1.5587×, 1.5457× and 1.5449× versus pristine normal. These timestamped fixtures are separate from canonical empty scripts.
- Peak RSS: GNU time, four workloads, 50 rounds and a same-binary control; 1,400 launches.

## Linux Bun comparison

This separate reference phase uses `-e ';'` with verified empty stdout. Bun's empty-string help path is not timed as JavaScript.

| Workload | Pristine normal, ms | Selected fork, ms | Release Node, ms | Bun, ms |
| --- | ---: | ---: | ---: | ---: |
| Empty CJS | 22.619 | 14.808 | 21.617 | 11.092 |
| Empty ESM | 23.009 | 15.235 | 22.185 | 11.057 |
| No-op eval | 23.188 | 15.096 | 22.657 | 10.912 |
| Hello | 27.231 | 18.135 | 26.061 | 10.925 |

Bun remains faster on these four Linux workloads. Release Node is a different revision/build, not the source-attribution control. These Linux results do not update the frozen macOS or Windows artifacts.

## Regression assessment

No selected ThinLTO PGO-versus-normal-pristine throughput interval was wholly below one in this selection. The selected build improved small SHA-256 by 33.4%, random bytes by 39.7%, HTTP parsing by 76.6%, URL parsing by 26.9%, file stat by 12.5% and Windows-1252 decoding by 3.7%; bulk SHA-256 was effectively unchanged.

The baseline matters. Against separately trained pristine PGO, non-LTO fork PGO was slower in file read (0.9905×), file stat (0.9805×) and uncached modules (0.9879×), with intervals excluding one. These roughly 1–2% losses are retained and disclosed. The earlier combined-source decoder loss did not reproduce: its final source increment was 1.0081× [1.0048, 1.0108].

Selected peak RSS medians were 46,158 KiB for CJS, 47,934 KiB for ESM, 46,608 KiB for eval and 59,080 KiB for a worker. Pristine-normal medians were 62,720, 63,554, 59,492 and 70,644 KiB. Transient dictionary and back-reference allocations still cost memory even though the final compiler recipe lowers measured peak RSS.

These are finite workload measurements, not a universal no-regression guarantee. The [independent raw-data audit](linux-renewed/final-v1/audits/raw-review.json) recomputed key confidence intervals and checked sample coverage, artifact identity, positive controls and same-binary controls.

## Compatibility

Combined normal, combined PGO and combined ThinLTO PGO each passed the 6,144-case Linux release-suite plan: 387 skips, 10 TODO annotations and zero unexpected failures, plus 238 native C++ tests. Pristine PGO passed its 6,142-case plan with the same skip/TODO counts and zero unexpected failures, plus 226 native tests.

Gates covered addon, Node-API, FFI, SQLite and embedding fixtures, documentation build and selected documentation tests. Artifact hashes remained unchanged. The [completed fork CI](CI.md) passed all six Linux/macOS jobs, while both Windows jobs failed the same four JavaScript tests; these local Linux passes do not make the whole fork CI green.

## Evidence and reproduction

- [Retention and rejection decisions](linux-renewed/final-v1/DECISIONS.md): measured value, costs and the closed investigated queue.
- [22-patch source package](linux-renewed/final-v1/source-package/README.md): original 18 patch files unchanged; complete replay and 64 source-file identities verified.
- [Package audit](linux-renewed/final-v1/audits/package-review.md): caught and rechecked the corrected series-file delimiter defect; subset application is not subset runtime validation.
- [Reproduction guide](linux-renewed/final-v1/REPRODUCE.md) and [artifact manifest](linux-renewed/final-v1/ARTIFACTS.json): source bundles, profiles, configurations and actual executable identities.
- [Final inventory](linux-renewed/final-v1/inventory-coverage.json): all 2,898 evidence files preserved, representing 12,609,624,953 uncompressed bytes across verified archives.
- [Owned resource cleanup](linux-renewed/final-v1/cleanup.json): VM, auto-delete disk, firewall, subnet and network removed after retrieval; unrelated resources untouched.

The host was Intel Ice Lake on GCE n2-standard-16, Ubuntu 24.04, Clang/LLD 20.1.8, Rust 1.89 and Python 3.12.3. Own builds and tests were idle during timing. Production source/build files match the public branch; newer test-only formatting and ICU dependency fixes were checked separately.
