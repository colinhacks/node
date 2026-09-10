# Snapshot uint30 loads

This candidate replaces four little-endian byte loads with V8's existing unaligned little-endian reader. It preserves the snapshot format, four-byte read bound, length mask and input position.

## Evidence

The retained Linux fork's `ReadObject` assembly uses three loads and shifts/ORs for this decode. A standalone probe compiling the actual header with the same Clang 20.1.8 emits one 32-bit load for the candidate. Apple Clang also collapses four ARM64 byte loads to one word load.

- Both original and candidate headers pass 132,768 boundary, alignment, trailing-byte and pseudorandom cases on native Linux x64 and macOS ARM64.
- Both also pass those cases with AddressSanitizer and UndefinedBehaviorSanitizer.
- The test covers every encoded width, offsets 0–7, all 256 following-byte values at width boundaries, and the maximum uint30 value.
- Added Node native tests also exercise round trips through the real `SnapshotByteSink`. Those tests and a complete candidate Node build are still pending.
- The existing helper handles big-endian targets explicitly. No big-endian hardware run has been performed.

These are correctness and code-generation results, not a measured Node startup improvement. Retention requires matched native binary measurements and compatibility tests.

## Files

- [Candidate generator](make_candidate.py) writes a separate header and [patch](candidate.patch), leaving the source checkout unchanged.
- [Standalone probe](uint30_probe.cc) includes the actual original or candidate V8 header.
- [Native tests](test_snapshot_uint30.cc) are appended to the candidate patch.
- [Linux probe recipe](run-header-probe.sh) records Clang version, input hashes, native tests, sanitizers and assembly differences.

The portable recipe accepts a pinned source checkout and an empty output directory. Captured probe output remains archived; see [`../ARCHIVED-EVIDENCE.md`](../ARCHIVED-EVIDENCE.md). The standalone probes were run during the control build, so their elapsed times are not benchmark evidence.
