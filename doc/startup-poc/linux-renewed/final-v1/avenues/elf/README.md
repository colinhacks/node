# Linux ELF loader investigation

## Result

`DT_RELR` packing is the highest-value native-loader experiment. The retained no-PGO ThinLTO control has 112,854 `R_X86_64_RELATIVE` relocations. Their `RELA` entries occupy 2,708,496 bytes. A greedy RELR encoding of those offsets occupies 24,736 bytes: a 99.09% reduction for that relocation class. The final fork has the same loader-facing relocation counts and tables as that control.

This does not predict a launch-time win. The dynamic loader must still map the binary, resolve non-relative relocations, run constructors, and Node must initialize V8 and its snapshot. It is nevertheless a materially different cost surface from the rejected PGO recipe and the existing ThinLTO-only control.

## Evidence

| Artifact | Relative relocations | Relative `RELA` bytes | Estimated RELR bytes | Estimated reduction |
| --- | ---: | ---: | ---: | ---: |
| Source baseline | 113,309 | 2,719,416 | 24,912 | 99.08% |
| ThinLTO control | 112,854 | 2,708,496 | 24,736 | 99.09% |

- The archived Linux record identifies the exact binaries, host, and no-PGO/no-hidden-visibility ThinLTO conditions. It reports 18.305–18.586 ms source-fork empty starts and 18.359–18.707 ms ThinLTO starts.
- The archived ThinLTO dynamic-table dump reports `RELACOUNT=112854`, `RELASZ=2747616`, `BIND_NOW`, and no `DT_RELR`. See [`../ARCHIVED-EVIDENCE.md`](../ARCHIVED-EVIDENCE.md).
- Existing flags already retain immediate binding ([`node.gypi:391-394`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/node.gypi#L391-L394)). Linux ThinLTO is scoped to static Node builds with Clang and LLD ([`common.gypi:216-219`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/common.gypi#L216-L219); [`configure.py:2120-2162`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/configure.py#L2120-L2162)).
- The PGO rejection is bounded: its reproduced Buffer/decoder losses do not establish that RELR, a different linker output format with no profile-guided code layout, is unsafe (see [`../ARCHIVED-EVIDENCE.md`](../ARCHIVED-EVIDENCE.md)).

## Experiment 1 — `DT_RELR` packing

Build a pristine ThinLTO control and an otherwise-identical candidate with the proposed linker addition in [`relr-linker-flag.patch`](relr-linker-flag.patch) (or equivalently `LDFLAGS=-Wl,-z,pack-relative-relocs` for a throwaway build). Do not combine it with PGO, private visibility, order files, or source changes.

1. Run [`elf_startup_probe.py`](elf_startup_probe.py) on both binaries before timing. The candidate must have `RELRSZ`/`RELR`, no longer carry the packed relative entries in `.rela.dyn`, and preserve `BIND_NOW`, PIE, RELRO, GNU stack state, `DT_NEEDED`, and all dynamic public C/N-API exports.
2. Capture `LD_DEBUG=statistics` for CJS, ESM, and eval arms. It separates glibc startup and relocation time from the process-level timing but is diagnostic only; do not compare its absolute cycles with normal runs.
3. Run the existing randomized 350-round launch harness and same-artifact controls. Retain the 14-workload rate gate and native addon/embedding selection because the candidate changes executable ELF metadata, not Node semantics.
4. Negative controls: the same build with `-Wl,-z,nopack-relative-relocs`; a non-RELR baseline; and a deliberately unsupported old dynamic loader. The final control demonstrates that linker-only ThinLTO can move latency slightly in the wrong direction, so an ELF-size reduction alone cannot retain this change.

### Compatibility gate

`DT_RELR` requires loader support. Treat this as an experimental Linux build for glibc 2.36 or later, not a retained default. The retained Ubuntu 24.04 artifacts already request up to `GLIBC_2.39`, so the prior VM pair cannot establish broad distribution compatibility. Test the intended Node binary support floor explicitly before adopting this flag. If the project needs loaders that do not parse `DT_RELR`, do not emit it in the general Linux artifact; a documented opt-in build mode remains possible. The test matrix must include the chosen oldest glibc, musl if supported, and the existing addon fixture matrix.

### Expected cost surface

The candidate can reduce binary pages read for relative relocation metadata by about 2.58 MiB and replaces over 112,000 24-byte entries with roughly 3,092 eight-byte words. It cannot remove the writes to relocated targets. A measurable sub-millisecond to low-millisecond warm-cache effect is plausible; a 2x process-launch claim is unsupported until loader statistics and paired timing show it.

## Experiment 2 — hidden C++ implementation symbols without PGO

The existing private-symbol experiment was built only in the rejected PGO/ThinLTO context. Its visibility patch already restricts hiding to C++ implementation compilation and validates generated flags. Re-run that narrowly on the no-PGO ThinLTO pair, with the exact old-addon probes retained. It is distinct from RELR but lower priority because ThinLTO already reduces weak emissions from 6,254 to 648 and the PGO-context incremental startup effect was only 0.5–0.8%.

The risk is C++ add-ons or programs that rely on incidental executable exports. Preserve all public C/N-API exports and reject the candidate on any prebuilt-addon failure. The existing report correctly treats weak-symbol and one-addon results as bounded evidence (see [`../ARCHIVED-EVIDENCE.md`](../ARCHIVED-EVIDENCE.md)).

## Rejected alternatives

- **GNU hash style:** all retained artifacts already contain `DT_GNU_HASH`; no separate SysV hash table exists, so changing hash style has no remaining table to remove.
- **Dropping `-z now`:** could defer PLT binding but weakens an existing hardening policy and shifts work into later calls; it is not a startup optimization acceptable under the stated security constraint.
- **`-Bsymbolic` / semantic-interposition flags:** an executable’s broad C++ dynamic export surface and external embedding/add-on relationships make their interposition assumptions too broad for a first renewed experiment. Visibility needs the narrower, tested export audit above.
- **Padding or forced addresses:** previous diagnosis already found placement sensitivity but correctly rejected a single favorable address as a repair (see [`../ARCHIVED-EVIDENCE.md`](../ARCHIVED-EVIDENCE.md)).

## Running the probe

On the Linux worker:

```sh
python3 elf_startup_probe.py \
  --output /tmp/thin-control-loader.json path/to/node -- -e ''
python3 elf_startup_probe.py \
  --output /tmp/relr-loader.json path/to/node-relr -- -e ''
```

The probe is intentionally read-only. It records the binary SHA-256 and size, bounds each subprocess with `--timeout` (30 seconds by default), removes inherited `NODE_*`, `__NUB_*`, and `LD_*` variables, and sets only `LD_DEBUG=statistics`. It records raw glibc statistics text because labels differ across loader versions.
