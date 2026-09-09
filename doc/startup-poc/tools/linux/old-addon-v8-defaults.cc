#include <cstdlib>
#include <memory>

#include "node_api.h"
#include "v8-array-buffer.h"
#include "v8-inspector.h"
#include "v8-platform.h"

class AllocatorProbe final : public v8::ArrayBuffer::Allocator {
 public:
  void* Allocate(size_t length) override { return std::calloc(1, length); }
  void* AllocateUninitialized(size_t length) override {
    return std::malloc(length);
  }
  void Free(void* data, size_t) override { std::free(data); }
  // Inherit GetPageAllocator(), whose public header default returns nullptr.
};

class PlatformProbe final : public v8::Platform {
 public:
  int NumberOfWorkerThreads() override { return 0; }
  std::shared_ptr<v8::TaskRunner> GetForegroundTaskRunner(
      v8::Isolate*, v8::TaskPriority) override {
    return nullptr;
  }
  double MonotonicallyIncreasingTime() override { return 0; }
  double CurrentClockTimeMillis() override { return 0; }
  v8::TracingController* GetTracingController() override { return nullptr; }

 protected:
  std::unique_ptr<v8::JobHandle> CreateJobImpl(
      v8::TaskPriority, std::unique_ptr<v8::JobTask>,
      const v8::SourceLocation&) override {
    return nullptr;
  }
  void PostTaskOnWorkerThreadImpl(v8::TaskPriority, std::unique_ptr<v8::Task>,
                                  const v8::SourceLocation&) override {}
  void PostDelayedTaskOnWorkerThreadImpl(v8::TaskPriority,
                                         std::unique_ptr<v8::Task>, double,
                                         const v8::SourceLocation&) override {}
  // Inherit GetThreadIsolatedAllocator(), whose public header default returns
  // nullptr.
};

napi_value RunProbe(napi_env env, napi_callback_info) {
  AllocatorProbe allocator;
  PlatformProbe platform;
  v8_inspector::V8InspectorClient inspector;

  // Base pointers require virtual dispatch. Compile this source at -O0 with no
  // LTO so an old addon exposes how its toolchain materializes these defaults.
  v8::ArrayBuffer::Allocator* allocator_base = &allocator;
  v8::Platform* platform_base = &platform;
  v8_inspector::V8InspectorClient* inspector_base = &inspector;
  bool result = allocator_base->GetPageAllocator() == nullptr &&
      platform_base->GetThreadIsolatedAllocator() == nullptr &&
      inspector_base->canExecuteScripts(0) &&
      inspector_base->generateUniqueId() == 0;

  napi_value value;
  napi_get_boolean(env, result, &value);
  return value;
}

napi_value NapiVersion(napi_env env, napi_callback_info) {
  uint32_t version = 0;
  napi_get_version(env, &version);
  napi_value value;
  napi_create_uint32(env, version, &value);
  return value;
}

napi_value Init(napi_env env, napi_value exports) {
  napi_value probe;
  napi_create_function(env, "probe", NAPI_AUTO_LENGTH, RunProbe, nullptr,
                       &probe);
  napi_set_named_property(env, exports, "probe", probe);

  napi_value version;
  napi_create_function(env, "napiVersion", NAPI_AUTO_LENGTH, NapiVersion,
                       nullptr, &version);
  napi_set_named_property(env, exports, "napiVersion", version);
  return exports;
}

NAPI_MODULE(NODE_GYP_MODULE_NAME, Init)
