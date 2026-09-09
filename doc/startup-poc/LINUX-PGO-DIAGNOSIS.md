# Linux PGO regression repeat

The measured shared-profile Linux PGO/ThinLTO recipe is rejected. A fresh 12-round, five-artifact repeat reproduced the two substantial throughput losses; all executable hashes remained unchanged.

| Workload | Source baseline | Pristine PGO control | Original-15 PGO fork | Entropy | Visibility |
| --- | ---: | ---: | ---: | ---: | ---: |
| Buffer creation, ops/s | 1,121,159 | 1,136,807 | 749,139 | 749,025 | 745,502 |
| Windows-1252 decode, ops/s | 51,280 | 29,766 | 35,243 | 35,086 | 34,787 |

These are median operation rates, not medians of paired ratios. The [report](linux-pgo-followup-v1/evidence/targeted-throughput/report.json.gz) retains the paired intervals; the [raw records](linux-pgo-followup-v1/evidence/targeted-throughput/raw.jsonl.gz) include all samples and three warmups per arm/workload. The [package manifest](linux-pgo-followup-v1/manifest.json) records original and sanitized hashes.

- The pristine PGO control preserves Buffer throughput. That loss already appears in the original-15 optimized fork, before the entropy change.
- The pristine PGO control itself loses decoding throughput. The fork recovers some of it, but remains substantially slower than the source baseline.
- The experiment does not isolate PGO from ThinLTO or establish a single source-level cause. A separate ThinLTO-only experiment evaluates that build option without this profile.

Earlier source-only diagnosis demonstrated sensitivity to code placement. One favorable function address is not a defensible general repair, and no padding or forced-address patch is included. This is a rejection of the measured recipe, not a claim that all PGO training must regress these workloads.
