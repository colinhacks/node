#include "base.h"
extern "C" __attribute__((visibility("default"), noinline))
int dispatch(const Base* ptr) { return ptr->value(); }
