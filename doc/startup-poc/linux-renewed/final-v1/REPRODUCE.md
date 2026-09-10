# Linux renewal reproduction

The public package supports two different checks. Recorded replay verifies the published evidence bytes. Fresh reproduction rebuilds and retrains on another Linux host, so its profiles, executables, and measurements can differ.

## Recorded replay

The public package contains compressed raw results, reports, build configurations and logs, drivers, the combined profile, and source patches. It does not contain the private Linux archives, source bundles, or recorded executables.

Run the manifest verifier from a checkout of this branch. It fails for a missing payload, an unexpected size, a compressed-byte digest mismatch, or a declared uncompressed digest mismatch.

```sh
python3.12 doc/startup-poc/linux-renewed/final-v1/reproduction/verify_manifest.py
python3.12 -m unittest doc/startup-poc/linux-renewed/final-v1/tools/test_summarize_final_linux.py
python3.12 -B doc/startup-poc/linux-renewed/final-v1/reproduction/replay_recorded.py --output /tmp/linux-tables-replay
```

The replay validates raw coverage, medians, paired ratios, artifact identities and all 7,567 first-JavaScript records, then requires byte-identical tables. It preserves stored bootstrap intervals rather than independently resampling them. Output JSON hashes refer to public redacted inputs; the [sanitization ledger](SANITIZATION.md) maps original and public bytes.

The local-only verifier at `startup-lab/platform/linux-renewed/final-reproduction-v1/verify_recorded_artifacts.py` validates private archives and binaries. It is not part of this public reproduction path.

## Source package

The source package records 22 patches and its expected tree. Generate a fresh package first, then apply its series to a clean checkout at the recorded base.

```sh
export REPO=$PWD
export DOC="$REPO/doc/startup-poc/linux-renewed/final-v1"
export BASE=8af75451e9041cd6058080ad3d4a65546797b418
export WORK=/absolute/path/to/linux-renewal

python3.12 "$DOC/build-source-package-v1.py" --source "$REPO" --original "$REPO/doc/startup-poc/patches" --output "$WORK/source-package"
git clone "$REPO" "$WORK/combined"
git -C "$WORK/combined" checkout --detach "$BASE"
git -C "$WORK/combined" apply --index "$WORK/source-package"/*.patch
test "$(git -C "$WORK/combined" write-tree)" = 9526a6758f0d6a11b779afc556a7eb0a86da84f9
git -C "$WORK/combined" -c user.name='Local reproduction' -c user.email='local-reproduction@invalid' commit -m 'local: replay renewed Linux source package'
test -z "$(git -C "$WORK/combined" status --porcelain)"
```

The local commit makes the replayed tree clean for the training helper. It is unpushed, uses the documented dummy identity, and has no human DCO sign-off. The measured combined PGO tree is `d4663c8727f57a404c1744e549aa8186db5a74d8` / `878cefc7616672165f913da854bca91740443fc7`. The package-tree check establishes the patch replay, not that local commits, profiles, or measurements will match the recorded run.

## Toolchain and PGO builds

Use Ubuntu 24.04 with Clang/LLD 20.1.8, Rust 1.89, and Python 3.12. The PGO helper records 55 training cases and merges their raw profiles. It requires a clean Git source tree and an empty output directory.

```sh
export CC=clang-20 CXX=clang++-20 AR=llvm-ar-20 NM=llvm-nm-20
export CFLAGS=-g0 CXXFLAGS=-g0 LDFLAGS=-fuse-ld=lld
unset NODE_OPTIONS NODE_PATH BUN_OPTIONS LLVM_PROFILE_FILE LD_PRELOAD LD_LIBRARY_PATH
export PGO_HELPER="$DOC/reproduction/balanced_pgo_probe.py"
export LLVM_PROFDATA=/usr/lib/llvm-20/bin/llvm-profdata

cd "$WORK/combined"
python3.12 configure --ninja
ninja -C out/Release -j8 node cctest
cp out/Release/node "$WORK/node-combined-normal"
python3.12 configure --ninja --enable-pgo-generate
ninja -C out/Release -j8 node cctest
cp out/Release/node "$WORK/node-combined-instrument"
python3.12 "$PGO_HELPER" train --source "$WORK/combined" --node "$WORK/node-combined-instrument" --llvm-profdata "$LLVM_PROFDATA" --output "$WORK/combined-training"
python3.12 configure --ninja --enable-pgo-use --pgo-profile="$WORK/combined-training/node.profdata"
ninja -C out/Release -t commands node cctest > "$WORK/combined-use.commands"
python3.12 "$PGO_HELPER" verify-graph --graph-phase use --config config.gypi --commands "$WORK/combined-use.commands" --profile "$WORK/combined-training/node.profdata" --output "$WORK/combined-use.graph.json"
ninja -C out/Release -j8 node cctest
cp out/Release/node "$WORK/node-combined-pgo"
python3.12 configure --ninja --enable-thin-lto --enable-pgo-use --pgo-profile="$WORK/combined-training/node.profdata"
ninja -C out/Release -j8 node cctest
cp out/Release/node "$WORK/node-combined-thin-pgo"
```

The non-LTO PGO build and the ThinLTO PGO build use the same combined source tree and profile. The latter adds only `--enable-thin-lto`. The copied `node-combined-normal` binary is the combined matched non-PGO arm and uses no profile.

## Separately trained control

The pristine PGO control is not the normal combined baseline. Start another clean checkout at the recorded base, apply [`pristine-control.patch`](profiles/pristine-control.patch), then build, train, and use its own profile.

```sh
git clone "$REPO" "$WORK/pristine"
git -C "$WORK/pristine" checkout --detach "$BASE"
git -C "$WORK/pristine" apply --index "$DOC/profiles/pristine-control.patch"
git -C "$WORK/pristine" -c user.name='Local reproduction' -c user.email='local-reproduction@invalid' commit -m 'local: add pristine LLVM PGO plumbing'
test -z "$(git -C "$WORK/pristine" status --porcelain)"
cd "$WORK/pristine"
python3.12 configure --ninja
ninja -C out/Release -j8 node cctest
cp out/Release/node "$WORK/node-pristine-normal"
python3.12 configure --ninja --enable-pgo-generate
ninja -C out/Release -j8 node cctest
cp out/Release/node "$WORK/node-pristine-instrument"
python3.12 "$PGO_HELPER" train --source "$WORK/pristine" --node "$WORK/node-pristine-instrument" --llvm-profdata "$LLVM_PROFDATA" --output "$WORK/pristine-training"
python3.12 configure --ninja --enable-pgo-use --pgo-profile="$WORK/pristine-training/node.profdata"
ninja -C out/Release -j8 node cctest
cp out/Release/node "$WORK/node-pristine-pgo"
```

## Fresh measurements

Fresh measurement needs absolute paths, a newly collected host record, and newly built artifacts. Supply release Node and Bun separately; neither executable is published in this package. The final driver runs 350 startup rounds and 30 throughput rounds, so it is a new experiment rather than a replay. The pristine normal binary is the baseline; the combined normal binary is an additional matched non-PGO arm.

```sh
export RESULTS=/absolute/path/to/new-results
export REFERENCES=/absolute/path/to/references  # contains release-node and bun
python3.12 "$DOC/driver/measure-final.py" --source "$WORK/combined" --references "$REFERENCES" --output "$RESULTS/final" --final-label combined-thin-pgo --all-reference-artifacts \
  --artifact "baseline=$WORK/node-pristine-normal" \
  --artifact "combined-normal=$WORK/node-combined-normal" \
  --artifact "combined-pgo=$WORK/node-combined-pgo" \
  --artifact "pristine-pgo=$WORK/node-pristine-pgo" \
  --artifact "combined-thin-pgo=$WORK/node-combined-thin-pgo"
python3.12 "$DOC/reproduction/linux_memory.py" --output "$RESULTS/memory" --rounds 50 \
  --artifact "baseline=$WORK/node-pristine-normal" \
  --artifact "combined-normal=$WORK/node-combined-normal" \
  --artifact "combined-pgo=$WORK/node-combined-pgo" \
  --artifact "pristine-pgo=$WORK/node-pristine-pgo" \
  --artifact "combined-thin-pgo=$WORK/node-combined-thin-pgo"
```

The archived wrappers use historical paths, gates, and a recorded boot ID. They remain evidence of the recorded run, not portable commands for a new host.
