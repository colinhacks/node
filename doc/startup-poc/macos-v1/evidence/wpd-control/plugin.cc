#include "base.h"
class Foreign : public Base {
 public:
  int value() const override { return 7; }
};
extern "C" __attribute__((visibility("default")))
Base* create() { return new Foreign; }
