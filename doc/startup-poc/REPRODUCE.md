# Native reproduction

Build the same pinned source and toolchain for the control and fork. Keep the executables at separate immutable paths; the measurement scripts refuse an existing output directory and verify executable hashes before and after each run.

## Source reconstruction

The example assumes this proposal directory is available independently of the two source checkouts. Git application creates staged changes, not commits or DCO attestations.

```sh
BASE=8af75451e9041cd6058080ad3d4a65546797b418
PROPOSAL=/absolute/path/to/proposal
git clone https://github.com/nodejs/node.git baseline
git -C baseline checkout --detach "$BASE"
git clone --shared baseline candidate
git -C candidate checkout --detach "$BASE"
while read -r patch; do
  git -C candidate apply --index "$PROPOSAL/patches/$patch"
done < "$PROPOSAL/patches/series"
test "$(git -C candidate write-tree)" = 3166f9876aa2586b4008f7c722ba406e8258d44a
```

On native Windows, use equivalent PowerShell paths and set `core.autocrlf=false` before creating the checkouts to match the recorded VM's LF source files. The record separately identifies the TypeScript fixture whose expected behavior depends on CRLF checkout conversion.

## Linux source builds

The recorded source-only builds used Ubuntu 24.04 x64, Clang/LLD 20.1.8, Ninja, Python 3.12.3 and Rust 1.89.0. Both retained full ICU, snapshots, OpenSSL, WebAssembly and Temporal; no host-specific ISA tuning was used.

```sh
export CC=clang-20 CXX=clang++-20 AR=llvm-ar-20 NM=llvm-nm-20
export CFLAGS=-g0 CXXFLAGS=-g0 LDFLAGS=-fuse-ld=lld
unset NODE_OPTIONS NODE_PATH LLVM_PROFILE_FILE
mkdir artifacts
for source in baseline candidate; do
  (
    cd "$source"
    python3 configure --ninja --v8-enable-temporal-support
    ninja -C out/Release -j12 node cctest
  )
  cp "$source/out/Release/node" "artifacts/$source"
  cp "$source/config.gypi" "artifacts/$source-config.gypi"
done
sha256sum artifacts/baseline artifacts/candidate
```

Explicitly enabling Temporal makes a missing Rust toolchain fail rather than silently producing a reduced-feature binary. The measured VM also used `-g0` for both controls; this is a matched build choice, not an isolated startup patch.

## Optional Linux ThinLTO

The [final Linux comparison](LINUX.md) includes a separately optimized pristine control. Use new source directories and preserve the no-LTO executables before configuring either ThinLTO build.

```sh
git clone --shared baseline baseline-thin
git -C baseline-thin checkout --detach "$BASE"
git -C baseline-thin apply --index "$PROPOSAL/tools/linux/pristine-thinlto.patch"
git clone --shared baseline candidate-thin
git -C candidate-thin checkout --detach "$BASE"
while read -r patch; do
  git -C candidate-thin apply --index "$PROPOSAL/patches/$patch"
done < "$PROPOSAL/patches/series"
for source in baseline-thin candidate-thin; do
  (
    cd "$source"
    python3 configure --ninja --v8-enable-temporal-support --enable-thin-lto
    ninja -C out/Release -j12 node cctest embedtest
  )
  cp "$source/out/Release/node" "artifacts/$source"
  cp "$source/config.gypi" "artifacts/$source-config.gypi"
done
```

Use the same Clang/LLD environment as the source-only example. The pristine support patch changes only build plumbing. No PGO profile, hidden-symbol recipe or whole-program devirtualization flag is part of this Linux experiment. Both full builds took about 42 minutes on the recorded host.

The standalone addon probe compiles once against original headers without LTO, then loads unchanged on all three executables. It exercises inherited V8 virtual defaults and a Node-API control; run it in a fresh output directory.

```sh
OUT_DIR=/absolute/path/to/new-addon-probe CXX=clang++-20 \
bash "$PROPOSAL/tools/linux/run-old-addon-v8-defaults.sh" \
  /absolute/path/to/baseline \
  /absolute/path/to/artifacts/baseline \
  /absolute/path/to/artifacts/baseline-thin \
  /absolute/path/to/artifacts/candidate-thin
```

The [supplemental validation](validation-linux-supplement-v1/manifest.json) includes the native probe, its relocations, 187 preserved addon test cases per executable and the source-only shell/configuration diagnosis. Build old addon fixtures against the pristine checkout first, then run its `addons`, `js-native-api` and `node-api` selections with `tools/test.py --shell` pointing to each retained executable. Do not rebuild those fixtures between executable changes.

## Native Windows builds

The VM used Server 2022 x64, VS 2022 17.14.37614, MSVC 14.44.35207, Clang-CL 19.1.5, SDK 10.0.26100, Python 3.14.7, Rust 1.89.0 and NASM 3.01. Run the following from an activated VS 2022 developer terminal, independently in each checkout.

```bat
vcbuild.bat x64 vs2022 clang-cl full-icu v8temporal cctest binlog
```

The default configuration is Release. Do not substitute the `release` shorthand in a no-LTO control: that argument also enables scoped LTCG. Copy each resulting `Release\node.exe` and `config.gypi` to separate retained paths before changing build options.

The measured global ThinLTO recipe appends the following arguments. Preserve the no-LTO control and compare against an equally optimized pristine control as well as the fork.

```bat
vcbuild.bat x64 vs2022 clang-cl full-icu v8temporal cctest binlog thin-lto lto-jobs 8
```

Apply patch 17 to the optimized pristine test source too when testing external addon builds. It changes no Node compiler graph or executable bytes, but prevents private LTO flags from leaking into MSVC addons. This fixture-build support is recorded separately from the pristine executable identity.

## Measurements

Run the native scripts after all builds, tests and profiling on that host have stopped. Use at least baseline and candidate artifact labels; additional equally optimized controls and incremental variants can be supplied with repeated arguments.

```sh
TOOLS="$PROPOSAL/tools/native"
python3 "$TOOLS/fetch-references.py" --output /absolute/path/to/references
python3 "$TOOLS/measure-final.py" \
  --source /absolute/path/to/baseline \
  --artifact baseline=/absolute/path/to/artifacts/baseline \
  --artifact candidate=/absolute/path/to/artifacts/candidate \
  --final-label candidate \
  --references /absolute/path/to/references \
  --output /absolute/path/to/new-measurement
```

The same CLI runs with native Windows Python and Windows paths. It records 350 randomized rounds for 12 process-lifetime workloads, 30 rounds for 14 official in-process benchmarks, 350 first-JS diagnostic rounds and 200 rounds for separate release references. Bun is excluded from the first-JS diagnostic because its `hrtime` epoch is process-relative, unlike Node's OS clock epoch.

The CSV throughput benchmark includes Buffer creation/comparison, encoding, crypto, filesystem, streams, module loading, URL parsing and HTTP parsing. A successful harness verdict means output/exit/hash contracts passed; it does not mean every throughput ratio improved or every identity confidence interval includes parity.

## Compatibility gates

The native gate runner requires the retained artifact to match the checkout's current build output. Keep Linux project roots short enough for Unix-domain socket fixtures and do not move the temporary directory outside the project for snapshot-based tests.

```sh
python3 "$TOOLS/native-gates.py" \
  --source /absolute/short/source \
  --artifact /absolute/path/to/artifacts/candidate \
  --output /absolute/path/to/new-gates --jobs 8
```

This runner exercises the broad selected Node suites and retains failures, skips and TODOs. The proposed fork workflow separately uses upstream `make build-ci`/`make test-ci` and Windows `vcbuild` CI selections. Neither selection is the complete upstream platform fleet; configured FIPS, debug, sanitizers, alternate CPU architectures and the addon ecosystem need their own validation.

## Entropy compatibility probes

The POSIX differential probe distinguishes preserved behavior from intentional changes in failure timing. Run it on Linux or macOS with a pre-entropy control and its otherwise-matched entropy candidate; the report retains both binaries' hashes and every process result.

```sh
python3 "$PROPOSAL/tools/entropy/probe.py" \
  --control /absolute/path/to/pre-entropy-node \
  --candidate /absolute/path/to/entropy-node \
  --output /absolute/path/to/new-entropy-probe.json
```

The retained [probe evidence](entropy-validation-v1/manifest.json) includes the invalid-DRBG negative control, worker/secure-heap behavior and provider cases. Windows used the additive Node test and focused native tests instead of this POSIX process-group probe. Its secure-heap skip is retained, not counted as a Windows pass.

A Linux FIPS smoke used a locally built provider, not a certified distribution. The helper requires a configured Ninja Node source tree and creates a new evidence directory during the build phase:

```sh
FIPS_SOURCE=/absolute/path/to/configured/baseline
FIPS_OUTPUT=/absolute/path/to/new-fips-evidence
python3 "$PROPOSAL/tools/entropy/fips-provider.py" build \
  --source "$FIPS_SOURCE" --output "$FIPS_OUTPUT" --jobs 8
python3 "$PROPOSAL/tools/entropy/fips-provider.py" install \
  --source "$FIPS_SOURCE" --output "$FIPS_OUTPUT"
python3 "$PROPOSAL/tools/entropy/fips-provider.py" verify \
  --source "$FIPS_SOURCE" --output "$FIPS_OUTPUT" \
  --node /absolute/path/to/pre-entropy-node \
  --node /absolute/path/to/entropy-node
```

The check requires FIPS mode, random bytes and the expected SHA-256 result, and rejects MD5 availability under both `--enable-fips` and `--force-fips`. It is a bounded provider check, not validation of a certified deployment or every FIPS algorithm.
