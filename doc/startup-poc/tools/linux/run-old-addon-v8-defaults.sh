#!/usr/bin/env bash
# Build one no-LTO addon from pristine headers, then load it unchanged in each
# supplied executable. Run this script on the Linux guest, not this macOS host.
set -euo pipefail

if [[ $# -ne 4 ]]; then
  cat >&2 <<'USAGE'
usage: run-old-addon-v8-defaults.sh PRISTINE_HEADERS SOURCE_NODE PRISTINE_THIN_NODE FINAL_THIN_NODE

PRISTINE_HEADERS is the original Node source tree used to build the old addon.
The remaining arguments are executable paths. The addon is compiled once with
no LTO and then loaded unchanged by each executable.
USAGE
  exit 64
fi

headers=$1
shift
nodes=("$@")
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
out=${OUT_DIR:-"$PWD/out-old-addon-v8-defaults"}
addon="$out/old-addon-v8-defaults.node"
[[ ! -e "$out" ]] || { echo "refusing to replace output: $out" >&2; exit 73; }
mkdir -p "$out"

for required in "$headers/src/node_api.h" "$headers/deps/v8/include/v8-platform.h" \
                "$headers/deps/v8/include/v8-inspector.h"; do
  [[ -f "$required" ]] || { echo "missing header: $required" >&2; exit 66; }
done
for node in "${nodes[@]}"; do
  [[ -x "$node" ]] || { echo "not executable: $node" >&2; exit 66; }
done

compile=("${CXX:-c++}" -std=c++20 -O0 -fno-inline -fPIC -shared
  -DNODE_GYP_MODULE_NAME=old_addon_v8_defaults
  -I "$headers/src" -I "$headers/deps/v8/include"
  "$here/old-addon-v8-defaults.cc" -o "$addon")
printf 'compile:'; printf ' %q' "${compile[@]}"; printf '\n'
"${compile[@]}"

echo '== target weak definitions in the old addon =='
readelf --dyn-syms --wide "$addon" | c++filt | \
  grep -E 'ArrayBuffer::Allocator::GetPageAllocator|Platform::GetThreadIsolatedAllocator|V8InspectorClient::(canExecuteScripts|generateUniqueId)' || true

echo '== target undefined dynamic symbols in the old addon =='
readelf --dyn-syms --wide "$addon" | c++filt | \
  awk '/ UND / && /ArrayBuffer::Allocator::GetPageAllocator|Platform::GetThreadIsolatedAllocator|V8InspectorClient::/' || true

echo '== target dynamic relocations in the old addon =='
readelf --relocs --wide "$addon" | c++filt | \
  grep -E 'ArrayBuffer::Allocator::GetPageAllocator|Platform::GetThreadIsolatedAllocator|V8InspectorClient::' || true

for node in "${nodes[@]}"; do
  echo "== load: $node =="
  "$node" -e '
    const addon = require(process.argv[1]);
    if (addon.probe() !== true) throw new Error("V8 default probe failed");
    if (!Number.isInteger(addon.napiVersion()) || addon.napiVersion() < 1) {
      throw new Error("N-API control failed");
    }
    console.log(JSON.stringify({ probe: addon.probe(), napi: addon.napiVersion() }));
  ' "$addon"
done

echo "PASS: unchanged old addon loaded in ${#nodes[@]} executable(s)"
