# Linux source-final evidence

The source-final package contains completed Linux source measurements only. Its validator checks archive integrity and retained-summary consistency. It does not establish that every comparison is regression-free.

## Retained package

The package lives at `startup-lab/public-platform-pr/linux-source-v1`. Its manifest SHA-256 is `6e77e5a8a775b312bc1346bc951391bf0e898857a7fcbbf4e43d781df2d3429d`.

- Identity control: 100 rounds across three empty-start workloads.
- Startup: 350 rounds across 12 workloads.
- Throughput: 30 rounds across 14 workloads.
- First JavaScript: 350 rounds across CJS, ESM, and eval diagnostics.
- Release references: 200 rounds across four workloads.

The retained artifact identities are `baseline` `a74cb2a6f3dfec29874838867554b0e27c28ff0d79a520b87e278211963070e0`, `entropy` `e70434843e822b1d1aa836c627e2d1abcd9191a1419a065fae899e9a0cd40604`, and `original15` `cafb25ab05a279f898032de36d21d51cba0bd464cf53c5290f1582bd90a878f3`. The first-JavaScript identity control uses the same baseline binary twice.

## Startup latency

Ratios are baseline over entropy. Values greater than one indicate lower entropy-build latency for this process-lifetime metric.

| Workload | Median ratio | 95% bootstrap interval |
| --- | ---: | ---: |
| Empty CJS | 1.31518 | [1.30389, 1.32639] |
| Empty ESM | 1.30482 | [1.29128, 1.31705] |
| Empty eval | 1.35524 | [1.33133, 1.37303] |

The corresponding entropy-over-original15 ratios are 0.95397 for empty CJS, 0.95549 for empty ESM, and 0.95644 for empty eval. Those values show lower entropy-build latency on the empty workloads. First random and first SHA-256 did not establish a change: their ratios were 1.00362 [0.99841, 1.01200] and 1.00211 [0.99811, 1.00571].

## Throughput margins

Ratios are baseline over entropy. Values greater than one indicate higher baseline throughput and lower entropy-build throughput for these metrics.

| Workload | Median ratio | Entropy margin |
| --- | ---: | ---: |
| Windows-1252 decode | 1.01843 | about 1.8% lower |
| Cached module load | 1.03352 | about 3.2% lower |

The retained results show small workload-specific losses, not a large PGO regression claim.

## First JavaScript

The CJS baseline-over-identity `first_js_ms` ratio is 1.01333 with a 95% bootstrap interval of [1.00216, 1.02483]. The interval excludes one. This is a same-binary diagnostic difference, so it is a limitation of that diagnostic rather than evidence of a source-build improvement.

## Release references

The corrected reference phase retained 200 paired rounds for baseline, entropy, the released Node reference, and Bun. The corrected phase reused the source-final seed and artifact set; only the references directory changed to `references-v1`.

| Workload | Baseline over entropy | Entropy over release | Entropy over Bun |
| --- | ---: | ---: | ---: |
| Empty CJS | 1.30453 | 0.80260 | 1.56053 |
| Empty ESM | 1.29814 | 0.80491 | 1.61164 |
| Hello | 1.27476 | 0.81125 | 1.94674 |
| Empty eval | 1.34605 | 0.78813 | 1.61956 |

The retained report labels the reciprocal Bun relation as `bun_over_entropy`. The table computes `entropy_over_bun` directly from paired raw observations. For this latency metric, values above one mean entropy has higher latency than Bun.

## Initial reference failure

The initial reference phase failed before collecting samples because it used `references-v2` instead of the actual `references-v1` input. That failure remains part of the run history. The package includes the corrected reference-only recovery, not a repeat of the completed source measurements.
