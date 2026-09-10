// Exercise the actual SnapshotByteSource header without initializing V8.
#include <array>
#include <cstdio>
#include <cstdlib>

#include "src/snapshot/snapshot-source-sink.h"

using v8::internal::SnapshotByteSource;

extern "C" __attribute__((noinline)) uint32_t DecodeUint30(
    SnapshotByteSource* source) {
  return source->GetUint30();
}

static void Check(uint32_t value, int offset, uint8_t following) {
  std::array<uint8_t, 16> data;
  data.fill(following);
  const int bytes = value < (1u << 6)    ? 1
                    : value < (1u << 14) ? 2
                    : value < (1u << 22) ? 3
                                         : 4;
  uint32_t encoded = (value << 2) | (bytes - 1);
  for (int i = 0; i < bytes; ++i) {
    data[offset + i] = static_cast<uint8_t>(encoded);
    encoded >>= 8;
  }
  SnapshotByteSource source(reinterpret_cast<const char*>(data.data()),
                            static_cast<int>(data.size()));
  source.set_position(offset);
  if (DecodeUint30(&source) != value || source.position() != offset + bytes ||
      source.Peek() != following) {
    std::fprintf(stderr,
                 "uint30 mismatch: value=%u offset=%d bytes=%d\n",
                 value,
                 offset,
                 bytes);
    std::abort();
  }
}

int main() {
  const uint32_t boundaries[] = {0,
                                 1,
                                 62,
                                 63,
                                 64,
                                 65,
                                 16382,
                                 16383,
                                 16384,
                                 16385,
                                 4194302,
                                 4194303,
                                 4194304,
                                 4194305,
                                 (1u << 30) - 2,
                                 (1u << 30) - 1};
  uint64_t cases = 0;
  for (uint32_t value : boundaries) {
    for (int offset = 0; offset < 8; ++offset) {
      for (int following = 0; following < 256; ++following) {
        Check(value, offset, static_cast<uint8_t>(following));
        ++cases;
      }
    }
  }
  uint32_t state = 0x079695c4;
  for (int i = 0; i < 100000; ++i) {
    state = state * 1664525u + 1013904223u;
    Check(state & ((1u << 30) - 1), i % 8, state >> 24);
    ++cases;
  }
  std::printf("PASS %llu actual-header uint30 cases\n",
              static_cast<unsigned long long>(cases));
}
