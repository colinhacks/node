# Reproduction

The package supports auditing the retained measurements and building a new comparison. Exact historical executable reproduction is not promised: the original profile/order inputs are identified by hash but not distributed, and fresh training produces a new experiment.

## Evidence audit

Run from a checkout containing this package at `doc/startup-poc`:

```sh
python3 doc/startup-poc/tools/verify_evidence.py --bootstrap
python3 -m unittest discover -s doc/startup-poc/tools/tests -v
```

The verifier uses only Python's standard library. It decompresses reports and samples in memory, checks published hashes, and compares raw-sample statistics with the stored results. It does not rerun Node or prove that an executable was built from the recorded source.

## Source reconstruction

Keep both checkouts and all run outputs separate. The [15 diffs](patches/series) reconstruct the candidate; the [build-only control](controls/pristine-pgo.patch) reconstructs the same-revision baseline.

```sh
DOC="$PWD/doc/startup-poc"
WORK=/absolute/path/to/new-startup-experiment
BASE=8af75451e9041cd6058080ad3d4a65546797b418
mkdir -p "$WORK"
git clone https://github.com/nodejs/node.git "$WORK/candidate"
git -C "$WORK/candidate" checkout --detach "$BASE"
git clone --shared "$WORK/candidate" "$WORK/control"
git -C "$WORK/control" checkout --detach "$BASE"
while IFS= read -r patch; do
  git -C "$WORK/candidate" apply "$DOC/patches/$patch" || exit 1
done < "$DOC/patches/series"
git -C "$WORK/control" apply "$DOC/controls/pristine-pgo.patch"
```

The shared clone borrows Git objects from the candidate, so retain both checkouts. The source manifest's file hashes permit checking reconstruction before building.

## Fresh PGO training

Use macOS arm64, a matching Clang/LLVM toolchain, Python and Ninja. Choose explicit compiler paths and remove inherited runtime/build overrides before configuring; the example below intentionally uses no pre-existing profile or order file.

```sh
export CC="$(xcrun --find clang)"
export CXX="$(xcrun --find clang++)"
export CFLAGS=-g0 CXXFLAGS=-g0 TERM=xterm-256color
unset CPPFLAGS LDFLAGS LLVM_PROFILE_FILE
LLVM_PROFDATA="$(xcrun --find llvm-profdata)"
clean() { python3 "$DOC/tools/clean_env.py" "$@"; }

cd "$WORK/candidate"
clean ./configure --ninja --enable-thin-lto --enable-pgo-generate
clean ninja -C out/Release -j2 node
python3 "$DOC/tools/pgo_train.py" \
  --node "$WORK/candidate/out/Release/node" \
  --source "$WORK/candidate" \
  --llvm-profdata "$LLVM_PROFDATA" \
  --duration 15 --startup-rounds 100 \
  --output "$WORK/training"
```

The trainer runs the base revision's 11 sustained PGO scripts and 800 startup cases. It records command lines, tool/input hashes and merge results; training times are not benchmark results. The trainer and `clean` wrapper sanitize inherited `NODE_*`/`__NUB_*` variables.

Build both arms against that same new profile, preserving outputs in a common artifact directory:

```sh
mkdir "$WORK/bin"
for arm in candidate control; do
  cd "$WORK/$arm"
  clean ./configure --ninja --enable-thin-lto --enable-pgo-use \
    --pgo-profile "$WORK/training/node.profdata"
  clean ninja -C out/Release -j2 node cctest embedtest
  cp out/Release/node "$WORK/bin/$arm-node"
  cp config.gypi "$WORK/bin/$arm-config.gypi"
  python3 "$DOC/tools/record_build.py" \
    --source "$WORK/$arm" --binary "$WORK/bin/$arm-node" \
    --config "$WORK/bin/$arm-config.gypi" \
    --build-command 'configure --ninja --enable-thin-lto --enable-pgo-use; ninja -C out/Release -j2 node cctest embedtest' \
    --output "$WORK/$arm-manifest"
done
```

This comparison omits trained ordering and therefore is **not** a reproduction of the final 1.88–1.89× artifact. Shared/system-ICU configurations disable whole-program-vtable optimization; the retained static bundled configuration enables it. Record profile-mismatch warnings rather than assuming every function consumed its profile.

## Optional temporal ordering

The build option accepts `--use-darwin-order-file /absolute/path/to/order` for the static Darwin Ninja CLI link. A valid order must come from a matching temporal-profile training build, not a profile borrowed from another platform or Node revision.

- Build a separate instrumented candidate with the Clang toolchain's temporal profiling enabled (`-ftemporal-profile` in both C and C++ flags alongside PGO generation).
- Run the same trainer with `--temporal`. It gives each process a separate raw profile and preserves traces through both merge stages; ordinary online merging loses temporal traces.
- Build the corresponding PGO-use executable without ordering, then map the temporal profile to that actual binary:

```sh
python3 "$DOC/tools/temporal_order.py" \
  --profile /absolute/path/to/temporal-training/node.profdata \
  --binary /absolute/path/to/unordered-pgo-node \
  --llvm-profdata "$LLVM_PROFDATA" --nm "$(xcrun --find nm)" \
  --output "$WORK/order-mapping"
```

Reconfigure the candidate with the generated `startup-temporal.order`, rebuild, and record a new binary/manifest. Verify actual symbol placement and compare an unordered same-object control; merely accepting an order flag is not evidence of a gain. The mapper is Mach-O arm64-specific. This package contains the measured layout samples, but not the historical training profile/order file, every object archive, or a byte-for-byte toolchain environment.

## Compatibility checks

Run the candidate's native tests and Node selection after installing headers and generating/building addon fixtures. The pinned [Node build guide](https://github.com/nodejs/node/blob/8af75451e9041cd6058080ad3d4a65546797b418/BUILDING.md) supplies platform prerequisites.

```sh
cd "$WORK/candidate"
clean out/Release/cctest
clean make JOBS=2 NINJA_ARGS=node test/addons/.docbuildstamp
clean python3 tools/install.py install --headers-only \
  --dest-dir "$WORK/headers" --prefix /
for suite in test/addons test/js-native-api test/node-api test/sqlite test/ffi benchmark/napi; do
  clean python3 tools/build_addons.py --headers-dir "$WORK/headers" \
    --out-dir "$WORK/candidate/out/Release" "$suite"
done
clean python3 tools/test.py --mode=release --progress=tap -j2 \
  default pummel addons ffi js-native-api node-api embedding benchmark sqlite sea
clean make JOBS=2 NINJA_ARGS=node lint-cpp lint-py lint-js-ci
```

The upstream addon builder has its own concurrency defaults; `JOBS=2` does not cap that Python pool. Run in an isolated build environment. These commands do not replace native addon export/callback checks, alternate ICU/shared builds, arithmetic or framework differentials, or full platform CI.

## Startup measurement

Stop compilers and tests before timing. Pass direct frozen binaries, not shell wrappers or package-manager shims; use a new output directory and preserve every result.

```sh
python3 "$DOC/tools/startup_lab.py" \
  --node "$WORK/bin/candidate-node" \
  --baseline-node "$WORK/bin/control-node" \
  --bun /absolute/path/to/bun \
  --node-config "$WORK/bin/candidate-config.gypi" \
  --baseline-config "$WORK/bin/control-config.gypi" \
  --node-build-manifest "$WORK/candidate-manifest/manifest.json" \
  --baseline-build-manifest "$WORK/control-manifest/manifest.json" \
  --runs 350 --warmups 10 --seed 20260927 --timezone system \
  --output "$WORK/startup-run"
```

The harness requires Bun as a separate reference; it is not the same-source control. An optional `--release-node` supplies the fourth arm used in the historical final run. Defaults cover eight workloads; the worker fixture is Node-only. All measured and warmup samples are retained, including failures.

The harness randomizes runtime/workload order per round, pairs successful samples by round, and computes median ratios with 2,000-resample bootstrap intervals. Readiness markers are separate from process lifetime. Do not combine historical patch ratios, compare timings across unrelated hosts as patch effects, or relabel fresh training as the retained final artifact.

## Historical artifact identifiers

| Input | SHA-256 |
| --- | --- |
| Final executable | `f7845d078891ed853f9cdc0e7d38f105bd7bec9c7ac9d16a5978f6bc7a469d42` |
| Same-head control | `836ec5f8f76b35f46e8c7badd8d4a9e6a03fc6841d85155ffecf6232281f6eb8` |
| Shared PGO profile | `7640bd67bfd83b9a16fde46b43ac14ab0af8a8fb6a97403c175acd85439c0bb9` |
| CLI order file | `93709ebb3dd9f03c0eaffebdc8c4a16025e9e929777d15c406af4a04a63c3da0` |
