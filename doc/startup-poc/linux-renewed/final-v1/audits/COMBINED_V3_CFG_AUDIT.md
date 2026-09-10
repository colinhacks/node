# Combined PGO-use v3 CFG audit

## Verdict

The combined PGO-use v3 build passes the no-ThinLTO PGO graph and native checks. Its eight CFG/hash warnings are helper-only in this actual graph. None reaches final `node` or `cctest`.

Performance is outside this audit. The result does not establish a startup or throughput benefit.

| Check | Result |
| --- | --- |
| Build exit | `0` |
| Compiler errors | none found |
| `cctest` | 238 tests, 0 failures, 0 errors, 0 disabled |
| Profiled compiles | 4,721 of 4,721; 0 explicit exclusions |
| Final links | `node` and `cctest`; neither has an LTO flag |
| Runtime CFG warnings | none linked into `node` or `cctest` |

The machine-readable record is [`COMBINED_V3_CFG_AUDIT.json`](COMBINED_V3_CFG_AUDIT.json).

## Configuration and provenance

The use record names commit `d4663c8727f57a404c1744e549aa8186db5a74d8` and tree `878cefc7616672165f913da854bca91740443fc7`. The training report names the same commit. The retrieved source bundle has SHA-256 `39ceb7efb80c1ebfd5a3cf9439c93f3dd33b9d75ba00af18059aaaf9b0487269`, names that commit as `HEAD`, and its unbundled Git object locally resolves to that tree. This proves the immutable source tree used by the training record without requiring a separate training-side tree field.

| Item | Value | Verification |
| --- | --- | --- |
| Compiler | Clang `20.1` | `config.gypi` |
| PGO mode | use enabled; generate disabled | `config.gypi` |
| LTO mode | LTO and ThinLTO both disabled | `config.gypi` and graph scan |
| Profile | `node.profdata` | SHA-256 `5550e875db8b1b3da5545e45ea268548350e77ceb0527ce20571fa47c0ff39b9` independently rehashed locally |
| Commands graph | `ninja.commands` | SHA-256 `a71487639f064a61ef5ab95e540afb72f322b70952d8937f8d64f13105022a16` |
| Config | `config.gypi` | SHA-256 `9e78e0820f33b0e972aa756dbacd1e73ffccabd1799b95826e17d36696aa3630` |

The graph validator reports 4,721 profile-use compile commands, no compile exclusions, and two final links. Its profile path matches the retained profile manifest. The commands carry the pinned `-fprofile-use` path, and no inspected compile or final-link command carries `-flto`.

The frozen control archive has SHA-256 `60dbfb7e61934f048b60a66434b9dee071c537f1d271e042903dd8ef32aa0380`. Its verification record covers 212 payload files. Streaming the two embedded artifacts and hashing their bytes independently reproduced `node` SHA-256 `b47ddfdc12327738606b3b0214298847fde9d93718713f16a50ef0bb0c91ce54` and `cctest` SHA-256 `23d6312320a6feac4288ce3208161170464a35f20d4e14700fcf0c62ec83ca4e`, matching the embedded build manifest.

## CFG warning membership

The build log contains eight `function control flow change detected (hash mismatch)` diagnostics, 39 profile-unused-argument diagnostics, and 2,190 other compiler warnings. All remain recorded. The exit is zero and the log contains no compiler error.

| Log line | Object | Function | Actual final target | `node` / `cctest` member |
| --- | --- | --- | --- | --- |
| 226 | `bytecode_builtins_list_generator.generate-bytecodes-builtins-list.o` | `main` | `bytecode_builtins_list_generator` | no |
| 1,185 | `genccode.genccode.o` | `main` | `genccode` | no |
| 1,196 | `icupkg.icupkg.o` | `main` | `icupkg` | no |
| 1,255 | `gen-regexp-special-case.gen-regexp-special-case.o` | `main` | `gen-regexp-special-case` | no |
| 3,361 | `v8_init.setup-isolate-full.o` | `SetupIsolateDelegate::SetupHeap` | `mksnapshot` through `libv8_init.a` | no |
| 3,362 | `v8_init.setup-isolate-full.o` | `SetupIsolateDelegate::SetupBuiltins` | `mksnapshot` through `libv8_init.a` | no |
| 3,983 | `mksnapshot.mksnapshot.o` | `main` | `mksnapshot` | no |
| 7,242 | `openssl-cli.openssl.o` | `main` | `openssl-cli` | no |

The saved `mksnapshot` link contains `libv8_init.a` and `mksnapshot.o`. The final `node` and `cctest` links both contain `libv8_snapshot.a`, and neither contains `libv8_init.a` or `mksnapshot.o`. The production GYP definitions match that split: `v8_init` compiles `setup-isolate-full.cc`, while `v8_snapshot` compiles `setup-isolate-deserialize.cc`.

The warning classification is specific to this graph. A future warning must be resolved against its own object/archive/final-link membership. It must not be suppressed or treated as an automatic runtime profile failure.

## Limits

- This audit validates build configuration, graph forwarding, source/profile records, independently verified artifact bytes, native tests, and warning scope.
- Startup and steady-throughput retention remain separate measurements.
