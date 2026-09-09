#include <array>
#include <cinttypes>

#include "third_party/rapidhash-v8/secret.h"

#include "gtest/gtest.h"

#if !V8_USE_DEFAULT_HASHER_SECRET
namespace {
namespace control {
uint64_t mul_mod(uint64_t a, uint64_t b, uint64_t m) {
#if defined(__SIZEOF_INT128__)
  return static_cast<uint64_t>((static_cast<__uint128_t>(a) * b) % m);
#else
  uint64_t r = 0;
  while (b) {
    if (b & 1) {
      uint64_t r2 = r + a;
      if (r2 < r) r2 -= m;
      r = r2 % m;
    }
    b >>= 1;
    if (b) {
      uint64_t a2 = a + a;
      if (a2 < a) a2 -= m;
      a = a2 % m;
    }
  }
  return r;
#endif
}

uint64_t pow_mod(uint64_t a, uint64_t b, uint64_t m) {
  uint64_t r = 1;
  while (b) {
    if (b & 1) r = mul_mod(r, a, m);
    b >>= 1;
    if (b) a = mul_mod(a, a, m);
  }
  return r;
}

unsigned sprp(uint64_t n, uint64_t a) {
  uint64_t d = n - 1;
  unsigned char s = 0;
  while (!(d & 0xff)) {
    d >>= 8;
    s += 8;
  }
  if (!(d & 0xf)) {
    d >>= 4;
    s += 4;
  }
  if (!(d & 0x3)) {
    d >>= 2;
    s += 2;
  }
  if (!(d & 0x1)) {
    d >>= 1;
    s += 1;
  }
  uint64_t b = pow_mod(a, d, n);
  if (b == 1 || b == n - 1) return 1;
  for (unsigned char r = 1; r < s; ++r) {
    b = mul_mod(b, b, n);
    if (b <= 1) return 0;
    if (b == n - 1) return 1;
  }
  return 0;
}

unsigned is_prime(uint64_t n) {
  if (n < 2 || !(n & 1)) return 0;
  if (n < 4) return 1;
  if (!sprp(n, 2)) return 0;
  if (n < 2047) return 1;
  if (!sprp(n, 3)) return 0;
  if (!sprp(n, 5)) return 0;
  if (!sprp(n, 7)) return 0;
  if (!sprp(n, 11)) return 0;
  if (!sprp(n, 13)) return 0;
  if (!sprp(n, 17)) return 0;
  if (!sprp(n, 19)) return 0;
  if (!sprp(n, 23)) return 0;
  if (!sprp(n, 29)) return 0;
  if (!sprp(n, 31)) return 0;
  if (!sprp(n, 37)) return 0;
  return 1;
}

uint64_t wyrand(uint64_t* seed) {
  *seed += UINT64_C(0x2d358dccaa6c78a5);
  return rapid_mix(*seed, *seed ^ UINT64_C(0x8bb84b93962eacc9));
}

void make_secret(uint64_t seed, uint64_t* secret) {
  constexpr uint8_t c[] = {
      15,  23,  27,  29,  30,  39,  43,  45,  46,  51,  53,  54,  57,  58,
      60,  71,  75,  77,  78,  83,  85,  86,  89,  90,  92,  99,  101, 102,
      105, 106, 108, 113, 114, 116, 120, 135, 139, 141, 142, 147, 149, 150,
      153, 154, 156, 163, 165, 166, 169, 170, 172, 177, 178, 180, 184, 195,
      197, 198, 201, 202, 204, 209, 210, 212, 216, 225, 226, 228, 232, 240};
  for (size_t i = 0; i < 3; ++i) {
    uint8_t ok;
    do {
      ok = 1;
      secret[i] = 0;
      for (size_t j = 0; j < 64; j += 8)
        secret[i] |= static_cast<uint64_t>(c[wyrand(&seed) % sizeof(c)]) << j;
      if (secret[i] % 2 == 0) {
        ok = 0;
        continue;
      }
      for (size_t j = 0; j < i; ++j) {
        if (v8::base::bits::CountPopulation(secret[j] ^ secret[i]) != 32) {
          ok = 0;
          break;
        }
      }
      if (ok && !is_prime(secret[i])) ok = 0;
    } while (!ok);
  }
}
}  // namespace control

uint64_t next(uint64_t* state) {
  *state += UINT64_C(0x9e3779b97f4a7c15);
  uint64_t z = *state;
  z = (z ^ (z >> 30)) * UINT64_C(0xbf58476d1ce4e5b9);
  z = (z ^ (z >> 27)) * UINT64_C(0x94d049bb133111eb);
  return z ^ (z >> 31);
}

void expect_prime_matches(uint64_t n, const char* group) {
  EXPECT_EQ(detail::is_prime(n), control::is_prime(n))
      << group << " mismatch for " << n;
}

TEST(RapidhashSecret, SmallFactorRejectionMatchesBaseline) {
  for (uint64_t n = 0; n < UINT64_C(1) << 20; ++n) {
    expect_prime_matches(n, "exhaustive");
  }
  constexpr std::array<uint64_t, 25> edges = {0,
                                              1,
                                              2,
                                              3,
                                              4,
                                              5,
                                              2045,
                                              2046,
                                              2047,
                                              2049,
                                              2053,
                                              3 * 683ULL,
                                              5 * 409ULL,
                                              7 * 293ULL,
                                              11 * 187ULL,
                                              13 * 157ULL,
                                              17 * 121ULL,
                                              19 * 109ULL,
                                              23 * 89ULL,
                                              29 * 71ULL,
                                              31 * 67ULL,
                                              37 * 59ULL,
                                              UINT64_MAX - 1,
                                              UINT64_MAX,
                                              UINT64_MAX - 2};
  for (uint64_t n : edges) expect_prime_matches(n, "edge");
  uint64_t state = UINT64_C(0x8e4d4c3b2a190817);
#if defined(__SIZEOF_INT128__)
  constexpr size_t kRandomPrimeCases = 20000;
  constexpr size_t kSecretCases = 2048;
#else
  constexpr size_t kRandomPrimeCases = 256;
  constexpr size_t kSecretCases = 32;
#endif
  for (size_t i = 0; i < kRandomPrimeCases; ++i) {
    expect_prime_matches(next(&state), "random");
  }
  for (size_t i = 0; i < kSecretCases; ++i) {
    uint64_t candidate[3];
    uint64_t baseline[3];
    const uint64_t seed = next(&state);
    rapidhash_make_secret(seed, candidate);
    control::make_secret(seed, baseline);
    for (size_t j = 0; j < std::size(candidate); ++j) {
      EXPECT_EQ(candidate[j], baseline[j]) << "seed " << seed;
    }
  }
}

}  // namespace
#endif  // !V8_USE_DEFAULT_HASHER_SECRET
