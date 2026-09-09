#include "base.h"
#include <dlfcn.h>
#include <cstdio>
class Local : public Base {
 public:
  int value() const override { return 42; }
};
int main(int argc, char** argv) {
  Local local;
  if (dispatch(&local) != 42) return 2;
  if (argc != 2) return 3;
  void* lib = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
  if (!lib) { puts(dlerror()); return 4; }
  auto create = reinterpret_cast<Base*(*)()>(dlsym(lib, "create"));
  if (!create) return 5;
  Base* foreign = create();
  int result = dispatch(foreign);
  printf("foreign=%d\n", result);
  delete foreign;
  return result == 7 ? 0 : 6;
}
