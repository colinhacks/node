# Linux renewal decisions

Retain the three measured V8 source changes and opt-in LLVM PGO support. Retain ThinLTO as an optional build choice: it adds a small startup gain to the new PGO recipe and improves several selected throughput workloads.

| Avenue | Decision | Evidence and cost |
| --- | --- | --- |
| Script-based source-position collection | Retain | Standalone empty-entry screen gained roughly 1.7–2.8%; tests cover streaming, code caches, snapshots and old LiveEdit functions. Private V8 test integration adds maintenance cost. |
| Bounded dictionary scratch | Retain | Standalone screen gained roughly 1.4–2.5%; up to 64 KiB dynamic scratch plus 1 KiB inline on 64-bit builds. Counts, holes, values, metadata and capacity boundaries are tested. |
| Bounded back-reference reservation | Retain | Roughly 0.5–1% screened startup improvement; eval interval included no change. Extra transient native allocation; the earlier worker RSS screen increased about 0.65%. |
| Balanced LLVM PGO | Retain, opt-in | Final same-source empty-entry gains about 9%; training and extra builds required. Separately trained pristine PGO and full throughput gates prevent attribution to the old rejected recipe. |
| ThinLTO with new PGO | Retain, opt-in | Adds 0.4–0.9% empty-entry speedup, with larger selected throughput gains. Same combined source/profile and only the ThinLTO flag changes. No pristine ThinLTO PGO control was built. |
| ELF RELR | Reject as default | [ELF investigation](avenues/elf/README.md): no convincing startup gain and a higher glibc floor. |
| Ordinary worker-pool readiness barrier removal | Reject | [Platform investigation](avenues/platform-barrier/README.md): neutral or slower timing. |
| Adaptive pool construction | Do not implement | [Measured budgets](avenues/platform-barrier/ADAPTIVE-POOL-TIMING-RESULTS.md): ordinary constructor median about 76 microseconds. Delayed readiness is separate and non-additive; empty launch posts delayed work. The observed budget does not justify added synchronization complexity. |
| Alternate uint30 and slot-copy paths | Reject | [Deserializer investigation](avenues/uint30/README.md): correctness checks passed, but timing was mixed or neutral. |
| Broad snapshot restoration | Do not implement | [Feasibility analysis](avenues/snapshot-bulk/FEASIBILITY.md): GC, map and fixup boundaries prevent treating restoration as unqualified bulk copying. No justified replacement emerged. |
| Bootstrap format-map gating | Reject | [Bootstrap analysis](avenues/bootstrap/README.md): the proposed shortcut violates default-enabled option behavior. |

The [full matrix](../../LINUX-RENEWED.md) measures the combined result directly. Standalone margins are not additive; the prior rejected PGO build and all earlier artifacts remain preserved.

The eight CFG warnings in both new PGO builds were traced to build helpers, not the linked Node or cctest runtime. They were inspected rather than suppressed: [normal PGO audit](audits/COMBINED_V3_CFG_AUDIT.md), [ThinLTO PGO audit](audits/THIN_PGO_V1_CFG_AUDIT.md).

The investigated, technically justified queue is complete. This is not a claim that every possible Node or V8 optimization has been exhausted, nor proof that the measured result is a fundamental ceiling. The retained changes have measured value without a serious user-facing regression found in the completed coverage; the remaining 1–2% PGO-control throughput losses and test/configuration limits are disclosed.
