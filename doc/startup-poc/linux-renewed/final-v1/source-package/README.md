# Renewed Linux source package

This package extends the frozen 18-patch series with four source-only patches. It does not add CI or documentation changes.

## Contents

| Patch | Published commit mapping | Minimal base closure | Additional closure after patch 18 |
| --- | --- | --- | --- |
| `19-build-linux-llvm-pgo.patch` | `e22d4673456e6dd59f2e246e9b2abd0e38151d5c` | patch 1 | none |
| `20-v8-collect-source-positions.patch` | `99d932a15875728562a62d65a2c0499af0d3953b`, source-position formatting from `1769a845456079ffea5bee4dc3503a55ba7f5a73`, ICU test dependency from `f788616cf1515e30a8cce13513dbe8b30e567904` | patches 1, 2, 9, 14, and 15 | none |
| `21-v8-bound-dictionary-rehash.patch` | `7efdf3f40841ab7b6ff8dcad2fc8f9ce7c8d42d6`, dictionary formatting from `1769a845456079ffea5bee4dc3503a55ba7f5a73` | patches 1, 2, 9, 14, 15, and 20 | patch 20 |
| `22-v8-size-deserializer-backrefs.patch` | `e0ecad7bc3c17754a8f1f522fb089e686e00ad33` | none | none |

The original patches `01` through `18` are copied byte-for-byte from `doc/startup-poc/patches`. Their recorded resulting tree is `3166f9876aa2586b4008f7c722ba406e8258d44a`.

## Reproduction

Run the generator against a checkout containing the listed commits. The output path must not already exist.

```sh
python3 doc/startup-poc/linux-renewed/final-v1/build-source-package-v1.py \
  --source . \
  --original doc/startup-poc/patches \
  --output /tmp/source-package-v1
```

The generator uses an isolated `GIT_INDEX_FILE`, initializes it with `git read-tree`, checks frozen patch digests, replays all 22 patches, and tests actual minimal closed subsets from base `8af75451e9041cd6058080ad3d4a65546797b418`. It separately tests the smaller context after frozen patch 18. Every selected base closure passes `git diff --cached --check`. The manifest compares every packaged non-documentation/non-workflow file hash with public head `f788616cf1515e30a8cce13513dbe8b30e567904`.

## Validation boundary

The manifest records complete replay, apply checks, and source identity. It does not establish a source build, runtime result, compatibility result, or combined performance result. Those require the separately controlled Linux build and benchmark artifacts.
