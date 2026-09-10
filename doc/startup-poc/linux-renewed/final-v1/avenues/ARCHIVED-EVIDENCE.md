# Archived Linux evidence

Some results in this directory were captured on a private Linux worker. The records below identify the archived input without publishing executables, VM paths, full process arguments, or raw logs.

| Report | Archived record | Publicly retained material | Boundary |
| --- | --- | --- | --- |
| Bootstrap | `OPTIMIZATIONS.md` measurements and the unmeasured built-in-record branch | Pinned Node source anchors | The prior measurements and branch are not published here. |
| ELF loader | `LINUX.md`, dynamic-table dumps, and PGO diagnosis | `elf_startup_probe.py` and `relr-linker-flag.patch` | The relocation counts and timing ranges are reported values. The ELF binaries and table dumps remain archived. |
| Platform timing | `platform-timing-v1`, tree digest `f5ec7d30208e6a5be4d4f1b81f9503a8d36d38060b0370febbc85a19f01058e8` | Scalar summaries, barrier patch, additive cctest, review, and test plan | The scalar file is a derived summary. Raw streams and the measured executable remain archived. |
| Snapshot bulk | Snapshot diagnostics, profile capture, capacity-census build log, and count transcript | Diagnostic patch, opcode-count extract, and back-reference model | Counts and pass totals are reported from archived records. The raw profile and build transcript remain archived. |
| Uint30 | Linux and macOS probe output | Generator, patch, probe, native test, and portable recipe | The reported compile and sanitizer observations are archived. No Node timing result exists. |

The source links in the avenue reports point to [`colinhacks/node` at `f788616c`](https://github.com/colinhacks/node/tree/f788616cf1515e30a8cce13513dbe8b30e567904). They support code-path claims. They do not turn archived measurements into public reproductions.
