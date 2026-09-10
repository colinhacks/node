# Snapshot bulk-restoration feasibility

## Decision

Do not implement a bulk-object restoration patch yet. The current snapshot bytecode is a recursive object graph program, not a relocatable heap image. A trusted, build-matched Node snapshot may accept a format change, but the smallest format change that could remove per-object work also needs a new heap-materialization protocol. The profile makes that investigation plausible; it does not identify which removable mechanism owns the observed time or establish the payoff for a protocol redesign.

The bounded alternative is to pre-size deserializer-owned vectors. It avoids only host-vector growth. It does not remove a heap allocation, map installation, tagged-slot initialization, bytecode interpretation, reference write, barrier, or object post-processing. The existing payload-length back-reference reservation experiment already describes that alternative; this investigation does not duplicate it as a source patch.

## Measured evidence and limits

The Linux diagnostic recorded 26,833 objects and 259,246 tagged slots in the 1,546,504-byte startup section, 8,211 objects and 38,469 slots in the 305,968-byte shared section, and 16,662 objects and 173,763 slots in the 614,640-byte context section. The startup section has 37,285 fixed-raw operations; the context has 19,409. Those counts establish that object construction and field restoration are material work. They do not estimate milliseconds.

The supplied profile records 0.322 ms for read-only restoration, 3.3275 ms for isolate restoration, and 3.3155 ms for context restoration. These intervals must not be added: they are diagnostic scopes, not proven disjoint CPU budgets. The 11.21% `ReadObject`, 6.03% plus 1.84% `ReadSingleBytecodeData`, and 1.94% `AllocateRawOrFail` samples are meaningful opportunity signals, but self-PC attribution across the profiled process is not a decomposition of `ReadObject` into allocation, initialization, graph decoding, barriers, or fixups. A future candidate must measure the individual phase and whole-process startup.

Existing measurements rule out adjacent representation changes: immutable generated snapshot metadata cost 46 microseconds, embedded built-in cache-map import 31 microseconds, and read-only dispatch-reference specialization 43 microseconds. The earlier flat-body encoding removed only 1.38% of context dispatches while enlarging its payload by 37.8%. Those measurements make another metadata sidecar or a lightly specialized interpreter a poor use of complexity.

## Why allocation cannot be bulked safely

`Deserializer::ReadObject` first recursively reads the map, refines the destination allocation for some strings, allocates one object in its selected space, installs its map, fills all tagged fields with a valid Smi, publishes an indirect handle in `back_refs_`, and only then recursively reads fields. The source explicitly permits field decoding to allocate or trigger a heap walk/GC. The prior object must already have a valid map, size, and tagged fields before the next allocation.

Consequences:

- A contiguous raw arena cannot be handed out before maps are decoded. Object sizes, required alignment, allocation space, shared-string routing, and large-object treatment are decided per object. `SnapshotSpace` distinguishes read-only, old, code, and trusted destinations.
- Raw addresses cannot replace `IndirectHandle` back-references. Recursive decoding can move objects; the existing handle is published before fields are read, and internalized user-snapshot strings can patch that handle to a thin-string target.
- Pre-initializing one large span is not equivalent to the current per-object initialization. GC iteration needs each map and valid tagged sentinel before a nested allocation. Ephemeron tables additionally need `undefined` in their elements; trusted objects may publish a self indirect pointer before a pending reference resolves.
- A generic raw copy is not valid for tagged fields. Fixed and variable raw data use relaxed atomic slot stores. Other operations resolve back-references, roots, startup/shared caches, weak and indirect prefixes, external references, API references, JS dispatch entries, and pending forward references through typed writes and barriers.
- Post-processing remains object-specific: strings may rehash/canonicalize, code fixes instruction starts, shared functions receive isolate-unique ids, typed arrays and buffers repair backing stores, external strings register native resources, and native contexts enter a weak list. These operations can release the no-GC scope.

The heap interface accepts one `AllocateRaw` request with one size, allocation type, alignment, and retry policy. Its slow path may expand a paged space or collect garbage. There is no deserializer-facing `reserve N bytes in each snapshot space and return uninitialized object ranges` API. Adding one would have to preserve page/LAB accounting, allocation observers, old-generation limits, code permissions, trusted-space state, and read-only heap sealing. It would still leave every object’s map, handle publication, fields, and fixups serial.

## Read-only, external, and user-data boundaries

Read-only snapshot data is restored before its pages are shared. References to it use page chunk and offset, rather than stable raw process addresses. The previous read-only promotion experiments caused custom V8 snapshot creation to crash despite passing Node CLI tests, so mapping or promotion is not a safe shortcut.

External/API references resolve against the receiving isolate’s external-reference table or supplied API table. Sandboxed values also carry an external-pointer tag. Trusted objects and code have their own snapshot spaces and fixups. A build-matched snapshot therefore is not a license to copy heap words unchanged across ASLR, isolate, or embedding state.

Node’s built-in startup data, V8 context snapshots, user-created snapshots, and script code caches are separate inputs. `Snapshot::Initialize` validates a blob version and checksum before restoring startup/read-only/shared sections; `NewContextFromSnapshot` separately restores a context and carries rehashability plus an embedder callback. Code-cache consumption has its own magic/version/flags/source/read-only-checksum validation and supports off-thread work. A startup-only sidecar must either be unavailable to user snapshots or be generated, validated, and tested on every one of these paths. Reusing a code-cache certificate would be incorrect.

## Diagnostic before a bulk candidate

The corrected, build-validated diagnostic is [`bulk-allocation-diagnostic.patch`](bulk-allocation-diagnostic.patch), rather than the earlier local draft. It adds one small snapshot-internal header with inline process-global atomics; it is included only by the three incrementing `.cc` files and `deserializer.cc`, does not modify `Heap`, and does not use a read-only-space heap pointer. Under the existing `--profile-deserialization` flag, it emits one additional line per deserializer. The line reports:

- `backref_reallocations` and `backref_relocated_entries`, measured directly around the two `back_refs_.push_back()` sites.
- `process_window_main_allocator_slow_paths`, incremented at `MainAllocator::AllocateRawSlow`, the exact point after a normal paged-space fast allocation has failed.
- `process_window_paged_space_expansions`, incremented only after `PagedSpaceBase::TryExpand` has allocated and linked a page.
- `process_window_read_only_space_growths`, incremented when `ReadOnlySpace::EnsureSpaceForAllocation` must obtain a page.

Each deserializer captures start and end snapshots of the process-global counters and prints their unsigned deltas; it never resets a shared counter. Those `process_window_*` fields are not attribution to a deserializer or worker: overlapping deserializers, or unrelated allocations while profiling is enabled, can contribute to their window. The main intended reading is a quiet, single-isolate startup process with the full transcript retained. They are not timing measurements. The patch does not count large-object allocation, host allocator work other than the back-reference vector, time spent in the slow path, or all allocations made by post-processing. A nonzero quiet-process slow-path or expansion count establishes a specific preallocation hypothesis. A zero can only exclude the mechanism actually covered by that counter; it never excludes map, initialization, interpreter, barrier, or post-processing work.

From the repository root, first verify the working patch with `git apply --check bulk-allocation-diagnostic.patch`. Run one quiet `--profile-deserialization -e ''` launch and retain the full transcript. Check that disabled launches emit no `SnapshotBulkAllocationStats` lines. Then collect the same diagnostic against the payload-length back-reference-reservation candidate and its same-revision control. Use `--no-node-snapshot` only as a fallback-mechanism control: it still loads V8's default snapshot. Repeat with a valid custom `--snapshot-blob` and the foreign-isolate custom-snapshot test before generalizing a built-in result. The timing decision remains an uninstrumented interleaved Linux comparison with RSS and regression controls.

## Actual capacity census

The corrected diagnostic was strictly applied, built, and exercised in archived Linux evidence. The archived build record reports 35 build steps and 236 passing tests. The archived count transcript supplies these non-user-code rows; see [`../ARCHIVED-EVIDENCE.md`](../ARCHIVED-EVIDENCE.md). The evidence patch and working patch have the same SHA-256: `08a8382c87830f30c0619ec8590ad3a1a6f9a1031ddb152b2ee976c19d104d31`.

| Section | Payload bytes | Backref reallocations | Relocated entries | Process-window slow paths | Process-window paged expansions | Process-window RO growths |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| startup/isolate | 1,546,504 | 4 | 30,720 | 9 | 7 | 0 |
| shared | 305,968 | 3 | 14,336 | 11 | 9 | 0 |
| context | 614,640 | 4 | 30,720 | 8 | 6 | 0 |

These rows establish that back-reference-vector relocation and ordinary paged-space slow-path/page-growth events occur in the sampled startup. They do not quantify their time, identify a worker, or provide a savings estimate; timing artifacts were contended and are not used here. The `process_window_*` columns retain their process-global per-deserializer-window limitation, so even this quiet-startup-oriented evidence is not a causal attribution.

`process_window_read_only_space_growths=0` has narrower coverage than the other two allocator counters. The hook is in `ReadOnlySpace::EnsureSpaceForAllocation`, but normal read-only snapshot restoration is a direct image protocol: `ReadOnlyHeapImageDeserializer::AllocatePage` calls `ReadOnlySpace::AllocateNextPage`/`AllocateNextPageAt` and then copies raw segments. Those methods bypass `EnsureSpaceForAllocation`. Thus zero does **not** show that read-only snapshot materialization performs no allocation or no work; it shows only that the ordinary `EnsureSpaceForAllocation` growth path was not observed. A separate direct-image page-allocation hook would be required before drawing an RO allocation conclusion.

## Smallest testable candidate, if evidence earns it

The only bounded candidate worth a timing build is the existing no-format-change reservation:

```cpp
const size_t capacity = clamp(source_.length() / 32, 2048, 32768);
back_refs_.reserve(capacity);
```

For the recorded sections it reserves 32,768, 9,561, and 19,207 entries, respectively, before recursive decoding. It removes estimated vector relocations only; its estimated extra peak storage is at most 240 KiB for one active deserializer, not a V8 heap allocation reduction. Treat the estimate as a model, not a speed claim. It is not advanced here because no uninstrumented paired Linux result or RSS result exists, and it cannot explain the `ReadObject` profile share.

If that isolated result is neutral, stop the vector-reservation route. If it is measurably positive, use the diagnostic to determine whether page growth or another mechanism accounts for it. A true sidecar-led bulk protocol is justified only by evidence that allocation slow paths or page expansion, rather than map/field/reference work, are material; no inherited microsecond threshold is a substitute for that evidence.

## Required verification for any future implementation

1. Test startup serializer once/twice, context serialization, custom blobs, large objects, typed arrays/buffers, embedder fields, external references, checksums, and corrupted blob rejection in `deps/v8/test/cctest/test-serialize.cc`.
2. Run Node’s retained native, addon/N-API, embedding, worker, `--snapshot-blob`, SEA, `--no-node-snapshot`, entropy, and explicit-V8-flag controls. Include foreign-isolate custom-snapshot creation because it caught the read-only regression.
3. Measure interleaved, same-revision uninstrumented Linux controls for empty CJS, ESM, eval, first JavaScript, worker startup, RSS, and the retained throughput suite. Keep phase timers diagnostic-only and report their overlap rather than summing them.

## Source anchors

| Claim | Source |
| --- | --- |
| Current object order, valid-state invariant, back-reference publication | [`deps/v8/src/snapshot/deserializer.cc:781-900`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/deps/v8/src/snapshot/deserializer.cc#L781-L900) |
| Fixed-raw fast path and generic bytecode dispatch | [`deps/v8/src/snapshot/deserializer.cc:988-1129`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/deps/v8/src/snapshot/deserializer.cc#L988-L1129) |
| Typed references, barriers, external/API references, and trusted self pointers | [`deps/v8/src/snapshot/deserializer.cc:1147-1539`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/deps/v8/src/snapshot/deserializer.cc#L1147-L1539) |
| Object-specific post-processing and GC release | [`deps/v8/src/snapshot/deserializer.cc:600-719`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/deps/v8/src/snapshot/deserializer.cc#L600-L719) |
| Allocation interface and slow-path GC behavior | [`deps/v8/src/heap/heap-allocator.h:47-74`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/deps/v8/src/heap/heap-allocator.h#L47-L74), [`deps/v8/src/heap/heap-allocator.cc:149-225`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/deps/v8/src/heap/heap-allocator.cc#L149-L225) |
| Snapshot section layout, validation, startup, and context routes | [`snapshot.cc:73-132`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/deps/v8/src/snapshot/snapshot.cc#L73-L132), [`:164-218`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/deps/v8/src/snapshot/snapshot.cc#L164-L218), [`:663-750`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/deps/v8/src/snapshot/snapshot.cc#L663-L750) |
| Separate code-cache compatibility contract | [`code-serializer.cc:460-516`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/deps/v8/src/snapshot/code-serializer.cc#L460-L516), [`:768-819`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/deps/v8/src/snapshot/code-serializer.cc#L768-L819) |
| Allocator slow and ordinary page-growth instrumentation points | [`deps/v8/src/heap/main-allocator.cc:196-239`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/deps/v8/src/heap/main-allocator.cc#L196-L239), [`deps/v8/src/heap/paged-spaces.cc:276-303`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/deps/v8/src/heap/paged-spaces.cc#L276-L303), [`deps/v8/src/heap/read-only-spaces.cc:372-394`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/deps/v8/src/heap/read-only-spaces.cc#L372-L394) |
| Direct read-only image page allocation, which bypasses the RO hook | [`deps/v8/src/snapshot/read-only-deserializer.cc:33-88`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/deps/v8/src/snapshot/read-only-deserializer.cc#L33-L88), [`deps/v8/src/heap/read-only-spaces.cc:576-604`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/deps/v8/src/heap/read-only-spaces.cc#L576-L604) |
| Historical flat-body and metadata rejections | Archived record; see [`../ARCHIVED-EVIDENCE.md`](../ARCHIVED-EVIDENCE.md) |
| Existing back-reference reservation model | [`BACKREF-RESERVATION.md`](BACKREF-RESERVATION.md) |
| Linux object/slot counts | [`OPCODE-COUNTS.json`](OPCODE-COUNTS.json), extracted from archived evidence |
