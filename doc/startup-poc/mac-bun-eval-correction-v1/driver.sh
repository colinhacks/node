#!/bin/sh
set -eu

ROOT=<HOME>/Documents/projects/mynode
LAB="$ROOT/startup-lab"
OUT="$LAB/platform/mac-bun-eval-correction-v1"

python3 "$LAB/startup_lab.py" \
  --node "$ROOT/artifacts/node-defensible-v1" \
  --baseline-node "$ROOT/artifacts/node-pristine-pgo-use" \
  --bun <HOME>/.bun/bin/bun \
  --node-config "$OUT/configs/config-defensible-v1.gypi" \
  --baseline-config "$OUT/configs/config-pristine-pgo-use.gypi" \
  --node-build-manifest "$OUT/configs/defensible-v1-manifest.json" \
  --baseline-build-manifest "$OUT/configs/pristine-pgo-use-manifest.json" \
  --runs 350 --warmups 10 --seed 20260927 --timeout 10 --timezone system \
  --workloads eval-empty --output "$OUT/evidence/main"

python3 "$LAB/startup_lab.py" \
  --node "$ROOT/artifacts/node-defensible-v1" \
  --baseline-node "$ROOT/artifacts/node-defensible-v1" \
  --bun <HOME>/.bun/bin/bun \
  --node-config "$OUT/configs/config-defensible-v1.gypi" \
  --baseline-config "$OUT/configs/config-defensible-v1.gypi" \
  --node-build-manifest "$OUT/configs/defensible-v1-manifest.json" \
  --baseline-build-manifest "$OUT/configs/defensible-v1-manifest.json" \
  --runs 350 --warmups 10 --seed 20260927 --timeout 10 --timezone system \
  --workloads eval-empty --output "$OUT/evidence/identity-control"
