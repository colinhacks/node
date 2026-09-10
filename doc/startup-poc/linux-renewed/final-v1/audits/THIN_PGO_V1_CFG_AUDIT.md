# ThinLTO PGO-use v1 CFG audit

## Verdict

The ThinLTO PGO-use arm is a valid matched ablation candidate. The build exited `0`, 238 `cctest` cases passed, and the no-LTO/ThinLTO helper found no pair error. Its `manual-review` status means warnings were retained for inspection. It does not identify a runtime PGO mismatch.

Performance remains outside this audit.

| Check | Result |
| --- | --- |
| Source | head `d4663c8727f57a404c1744e549aa8186db5a74d8`; tree `878cefc7616672165f913da854bca91740443fc7` in both arms |
| Profile | same path and SHA-256 `5550e875db8b1b3da5545e45ea268548350e77ceb0527ce20571fa47c0ff39b9` |
| Configuration delta | `enable_thin_lto` only |
| Compile source sets | 4,260 unique profile-use sources in each arm; zero explicit exclusions |
| Thin arm graph | 4,721 profile-use compiles and two final `node`/`cctest` links; all forward `-flto=thin`, final links also use `-fuse-ld=lld` |
| Build and native test | exit `0`; 238 tests, 0 failures, 0 errors, 0 disabled |
| Runtime CFG warnings | none |

The machine-readable record is [`THIN_PGO_V1_CFG_AUDIT.json`](THIN_PGO_V1_CFG_AUDIT.json).

## Warning decision

The actual Thin build log contains eight PGO CFG/hash diagnostics. Each resolves to a helper-only target in this Thin graph. The final `node` and `cctest` commands contain `libv8_snapshot.a`, not `libv8_init.a` or `mksnapshot.o`. The `setup-isolate-full.cc` pair therefore reaches `mksnapshot` through `libv8_init.a`, not a final runtime executable.

| Log line | Object | Final target |
| --- | --- | --- |
| 226 | `bytecode_builtins_list_generator.generate-bytecodes-builtins-list.o` | `bytecode_builtins_list_generator` |
| 1,182 | `genccode.genccode.o` | `genccode` |
| 1,199 | `icupkg.icupkg.o` | `icupkg` |
| 1,669 | `gen-regexp-special-case.gen-regexp-special-case.o` | `gen-regexp-special-case` |
| 3,254–3,255 | `v8_init.setup-isolate-full.o` | `mksnapshot` through `libv8_init.a` |
| 4,006 | `mksnapshot.mksnapshot.o` | `mksnapshot` |
| 7,233 | `openssl-cli.openssl.o` | `openssl-cli` |

No additional `function control flow change detected (hash mismatch)` diagnostic appears in the Thin build. The log also contains no ThinLTO/linker profile diagnostic, compiler error, `ld.lld` diagnostic, or LLVM fatal diagnostic.

The 39 `-fprofile-use` unused-argument warnings occur while compiling assembly-source commands. The command graph has 43 PGO-flagged `.s` or `.S` compiles, including OpenSSL assembly, libffi assembly, ICU data assembly, and V8 snapshot assembly. They show that Clang does not apply an IR PGO profile to those assembly inputs. They are not CFG mismatches in a C/C++ runtime translation unit.

The other 2,190 compiler warnings remain in the log. This audit does not relabel them as PGO failures because they are not profile CFG diagnostics and the build completed successfully.

## Artifact and measurement boundary

The retained build manifest records `node` SHA-256 `ffa49c64dc7ecc307c58252a4c38b5159b9a68c9d0c60247af609ca0c53b0ed0` and `cctest` SHA-256 `ddb5374ef75b126bb5b6540fe2536e96385c18cada5c50666f52a3c1d4054c37`. Subsequent archive retrieval independently rehashed both artifacts successfully; the original warning audit is retained locally unchanged.

This warning audit does not measure startup or steady throughput. The subsequent [final Linux report](../../../LINUX-RENEWED.md) records completed functional, performance and artifact-validation gates.
