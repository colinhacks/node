#include <cstdint>

#include "third_party/rapidhash-v8/secret.h"

#include "gtest/gtest.h"

#if !V8_USE_DEFAULT_HASHER_SECRET && defined(__SIZEOF_INT128__)
namespace {

uint64_t Next(uint64_t* state) {
  *state += UINT64_C(0x9e3779b97f4a7c15);
  uint64_t value = *state;
  value = (value ^ (value >> 30)) * UINT64_C(0xbf58476d1ce4e5b9);
  value = (value ^ (value >> 27)) * UINT64_C(0x94d049bb133111eb);
  return value ^ (value >> 31);
}

uint64_t MultiplyReference(uint64_t a, uint64_t b, uint64_t modulus) {
  return static_cast<uint64_t>((static_cast<__uint128_t>(a) * b) % modulus);
}

unsigned GenericSprp(uint64_t n, uint64_t a) {
  uint64_t d = n - 1;
  unsigned char s = 0;
  while (!(d & 1)) {
    d >>= 1;
    ++s;
  }
  uint64_t value = detail::pow_mod(a, d, n);
  if (value == 1 || value == n - 1) return 1;
  for (unsigned char r = 1; r < s; ++r) {
    value = detail::mul_mod(value, value, n);
    if (value <= 1) return 0;
    if (value == n - 1) return 1;
  }
  return 0;
}

bool IsSmallPrime(uint64_t n) {
  if (n < 2) return false;
  for (uint64_t divisor = 2; divisor <= n / divisor; ++divisor) {
    if (n % divisor == 0) return false;
  }
  return true;
}

void CheckMultiply(uint64_t a, uint64_t b, uint64_t modulus) {
  const detail::MontgomeryMod montgomery(modulus);
  const uint64_t actual = montgomery.FromMontgomery(montgomery.Multiply(
      montgomery.ToMontgomery(a), montgomery.ToMontgomery(b)));
  EXPECT_EQ(actual, MultiplyReference(a, b, modulus));
}

TEST(RapidhashMontgomery, HandlesOverflowEdges) {
  CheckMultiply(0, 0, 3);
  CheckMultiply(UINT64_MAX, UINT64_MAX, 3);
  CheckMultiply(UINT64_MAX - 1, UINT64_MAX - 2, UINT64_MAX);
  CheckMultiply(UINT64_C(1) << 63, UINT64_MAX, (UINT64_C(1) << 63) | 1);
  CheckMultiply(UINT64_MAX - 1, UINT64_MAX - 1, UINT64_MAX - 58);
}

TEST(RapidhashMontgomery, MatchesReferenceArithmetic) {
  for (uint64_t modulus = 3; modulus < 128; modulus += 2) {
    for (uint64_t a = 0; a < modulus; ++a) {
      for (uint64_t b = 0; b < modulus; ++b) {
        CheckMultiply(a, b, modulus);
      }
    }
  }

  uint64_t state = UINT64_C(0x0123456789abcdef);
  for (size_t i = 0; i < 4096; ++i) {
    const uint64_t modulus = Next(&state) | 1;
    CheckMultiply(Next(&state), Next(&state), modulus);
  }
}

TEST(RapidhashMontgomery, MatchesGenericPower) {
  uint64_t state = UINT64_C(0xfedcba9876543210);
  for (size_t i = 0; i < 4096; ++i) {
    const uint64_t modulus = Next(&state) | 1;
    const uint64_t base = Next(&state);
    const uint64_t exponent = Next(&state);
    const detail::MontgomeryMod montgomery(modulus);
    const uint64_t actual =
        montgomery.FromMontgomery(montgomery.Power(base, exponent));
    EXPECT_EQ(actual, detail::pow_mod(base, exponent, modulus));
  }
}

TEST(RapidhashMontgomery, MatchesGenericMillerRabin) {
  constexpr uint64_t bases[] = {2, 3, 5, 37};
  for (uint64_t n = 3; n < 4096; n += 2) {
    EXPECT_EQ(detail::is_prime(n), IsSmallPrime(n));
    for (uint64_t base : bases) {
      EXPECT_EQ(detail::sprp(n, base), GenericSprp(n, base));
    }
  }

  uint64_t state = UINT64_C(0xa5a5a5a5a5a5a5a5);
  for (size_t i = 0; i < 1024; ++i) {
    const uint64_t n = Next(&state) | 1;
    const uint64_t base = Next(&state);
    EXPECT_EQ(detail::sprp(n, base), GenericSprp(n, base));
  }
}

}  // namespace
#endif  // !V8_USE_DEFAULT_HASHER_SECRET && defined(__SIZEOF_INT128__)
