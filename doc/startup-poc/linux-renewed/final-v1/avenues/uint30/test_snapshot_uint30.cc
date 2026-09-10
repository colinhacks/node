#include <array>
#include <cstdint>

#include "gtest/gtest.h"
#include "src/snapshot/snapshot-source-sink.h"

namespace {

using v8::internal::SnapshotByteSink;
using v8::internal::SnapshotByteSource;

TEST(SnapshotUint30, LengthBoundariesAndUnalignedInput) {
  constexpr uint32_t values[] = {0,
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
  for (uint32_t value : values) {
    const int bytes = value < (1u << 6)    ? 1
                      : value < (1u << 14) ? 2
                      : value < (1u << 22) ? 3
                                           : 4;
    for (int offset = 0; offset < 8; ++offset) {
      for (int following = 0; following < 256; ++following) {
        std::array<uint8_t, 16> data;
        data.fill(static_cast<uint8_t>(following));
        uint32_t encoded = (value << 2) | (bytes - 1);
        for (int i = 0; i < bytes; ++i) {
          data[offset + i] = static_cast<uint8_t>(encoded);
          encoded >>= 8;
        }
        SnapshotByteSource source(reinterpret_cast<const char*>(data.data()),
                                  static_cast<int>(data.size()));
        source.set_position(offset);
        EXPECT_EQ(source.GetUint30(), value);
        EXPECT_EQ(source.position(), offset + bytes);
        EXPECT_EQ(source.Peek(), following);
      }
    }
  }
}

TEST(SnapshotUint30, SinkRoundTrip) {
  SnapshotByteSink sink;
  uint32_t state = 0x079695c4;
  for (int i = 0; i < 10000; ++i) {
    state = state * 1664525u + 1013904223u;
    sink.PutUint30(state & ((1u << 30) - 1), "test");
  }
  // The decoder reads four bytes even for a one-byte value.
  const int end = sink.Position();
  sink.PutN(3, 0xff, "padding");
  SnapshotByteSource source(reinterpret_cast<const char*>(sink.data()->data()),
                            sink.Position());
  state = 0x079695c4;
  for (int i = 0; i < 10000; ++i) {
    state = state * 1664525u + 1013904223u;
    EXPECT_EQ(source.GetUint30(), state & ((1u << 30) - 1));
  }
  EXPECT_EQ(source.position(), end);
}

}  // namespace
