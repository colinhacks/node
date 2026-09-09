#pragma once
#ifdef PUBLIC_LTO
#define LTO_PUBLIC [[clang::lto_visibility_public]]
#else
#define LTO_PUBLIC
#endif
class LTO_PUBLIC Base {
 public:
  virtual ~Base() = default;
  virtual int value() const = 0;
};
extern "C" __attribute__((visibility("default"))) int dispatch(const Base*);
