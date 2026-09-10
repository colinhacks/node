#!/usr/bin/env bash
set -euo pipefail
SOURCE=${1:?usage: run-header-probe.sh /path/to/node-source /path/to/output}
E=${2:?usage: run-header-probe.sh /path/to/node-source /path/to/output}
HERE=$(cd "$(dirname "$0")" && pwd)
P="$E/input"
mkdir -p "$P/include/src/snapshot" "$E"
python3 "$HERE/make_candidate.py" "$SOURCE/deps/v8/src/snapshot/snapshot-source-sink.h" \
  "$P/include/src/snapshot/snapshot-source-sink.h"
cp "$HERE/uint30_probe.cc" "$P/"
exec > >(tee "$E/run.log") 2>&1
clang++-20 --version
for variant in baseline candidate; do
  extra=()
  if [ "$variant" = candidate ]; then extra=(-I"$P/include"); fi
  includes=("${extra[@]}" -I"$SOURCE/deps/v8"
    -I"$SOURCE/deps/v8/include"
    -I"$SOURCE/deps/v8/third_party/abseil-cpp")
  clang++-20 -std=c++20 -O3 -DNDEBUG "${includes[@]}" \
    "$P/uint30_probe.cc" -o "$E/$variant-probe"
  "$E/$variant-probe"
  clang++-20 -std=c++20 -O3 -DNDEBUG "${includes[@]}" \
    -S "$P/uint30_probe.cc" -o "$E/$variant-x64.s"
  clang++-20 -std=c++20 -O2 -DNDEBUG -fsanitize=address,undefined \
    "${includes[@]}" "$P/uint30_probe.cc" -o "$E/$variant-sanitized"
  "$E/$variant-sanitized"
done
sha256sum "$SOURCE/deps/v8/src/snapshot/snapshot-source-sink.h" \
  "$P/include/src/snapshot/snapshot-source-sink.h" "$P/uint30_probe.cc" \
  > "$E/input.sha256"
diff -u <(sed -n '/DecodeUint30:/,/End function/p' "$E/baseline-x64.s") \
  <(sed -n '/DecodeUint30:/,/End function/p' "$E/candidate-x64.s") \
  > "$E/decode-assembly.diff" || test $? = 1
cat "$E/decode-assembly.diff"
