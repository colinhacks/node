# Back-reference capacity experiment

`backrefs-capacity.patch` replaces the fixed 2,048-entry reservation for
`Deserializer::back_refs_` with a payload-size estimate clamped to
2,048–32,768 entries. It changes neither the snapshot format nor the
deserialization opcode stream.

## Evidence and hypothesis

The Linux `perf report --no-children` profile attributes 11.21% **self** samples
to `Deserializer<Isolate>::ReadObject`; it does not measure inclusive time.
`WriteHeapPointer` contributes 2.73% self, `AllocateRawOrFail` 1.94%, and
`PostProcessNewObject` 1.76%. The prior raw-slot loop candidate was tested on
Linux and showed no established startup improvement, so this experiment targets
different work: growth and relocation of the back-reference vector.

`opcodes-v2.json` records these payload/object pairs for the profiled Node
startup deserializers:

| Section | Payload bytes | Objects/back references | Patch reservation |
| --- | ---: | ---: | ---: |
| Built-in startup | 1,546,504 | 26,833 | 32,768 |
| Shared heap | 305,968 | 8,211 | 9,561 |
| Context | 614,640 | 16,662 | 19,207 |

Those sections executed 151,287, 34,500, and 138,375 opcodes respectively;
the built-in and context sections contained 37,285 and 19,409 fixed-raw-data
opcodes. The candidate does not change those opcode paths.

The estimate uses 32 payload bytes per back reference, below the observed
36.9–57.6 bytes per object across those three sections. Therefore each recorded
section fits within its initial reservation. With typical doubling growth, the
old 2,048-entry reservation would relocate an estimated 30,720 entries for the
built-in and context sections and 14,336 for shared; this is an allocator model,
not a V8 guarantee.

## Source anchors and rejected removals

In retained V8 source `deps/v8/src/snapshot/deserializer.cc`, the fixed
reservation is at line 349; `ReadObject` allocates, installs the map, and fills
tagged fields at lines 781–836, then creates and records the back-reference
handle at lines 876–884. `ReadMetaMap` records the same kind of handle at lines
904–926. `GetBackReferencedObject` reads that handle and adds it to the hot
object list at lines 743–753, while `ReadNewObject` and `ReadBackref` write the
result through `WriteHeapPointer` at lines 1151–1184. Allocation itself is
centralized at lines 1698–1718. These anchors rule out safely deleting
per-object allocation, the handle, initialization, or pointer writes.

## Correctness boundary

The patch retains `IndirectHandle<HeapObject>` entries, per-object handle
allocation, `MemsetTagged` initialization, map installation, recursive reads,
all `WriteHeapPointer` calls and barriers, and `PostProcessNewObject`.
`ReadObject` must publish a relocation-safe handle before `ReadData`, because
recursive reads can allocate and trigger GC. Replacing the vector with raw
object addresses, avoiding the handle, skipping initialization, or bulk-copying
tagged destinations would violate that boundary. No serialized bytes, format
version, ASLR/user-seed behavior, snapshot flags, workers, or embedding paths
change.

The maximum adds at most 30,720 entries beyond the old reservation per active
deserializer (about 240 KiB when an `IndirectHandle` is one pointer). This is
deliberately bounded; atypical high-object-density payloads may still grow and
should only lose the intended allocation benefit, not correctness. Smaller
payloads retain the existing 2,048-entry reservation.

## Focused probe and verification

Run the model check against the recorded diagnostic artifact:

```sh
python3 backrefs_capacity_probe.py OPCODE-COUNTS.json
```

After applying the patch in an isolated Linux source copy, also pass `--source`
with that copy's `deps/v8/src/snapshot/deserializer.cc` to verify the constants
and reservation call. Then rebuild the exact Node configuration, run snapshot
and deserializer cctests, and run the unchanged matched startup screen. Treat a
speedup as unproven until its confidence interval excludes neutral; monitor
startup, worker, CJS, ESM, and eval paths for regressions. Compare peak RSS and
run ASan/UBSan if available.

## Patch coexistence

The hunk changes only `back_refs_.reserve(2048)` in
`deps/v8/src/snapshot/deserializer.cc`. It does not overlap the retained opcode
diagnostic patch, `copy-slots.patch`, `rehash-timing.patch`,
`isolate-snapshot-total.patch`, or sibling `uint30/candidate.patch` by textual
hunk range. Application in a clean temporary copy is still required before a
combined build.

The final patch replayed successfully with the retained opcode diagnostic,
`rehash-timing.patch`, and `isolate-snapshot-total.patch` in an owned temporary
source copy. That validates text applicability only; it is not a build or
runtime result.
