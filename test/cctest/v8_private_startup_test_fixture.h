#ifndef TEST_CCTEST_V8_PRIVATE_STARTUP_TEST_FIXTURE_H_
#define TEST_CCTEST_V8_PRIVATE_STARTUP_TEST_FIXTURE_H_

#include "gtest/gtest.h"
#include "node.h"
#include "uv.h"
#include "v8.h"

// Implemented by the ordinary Node-compiled bridge TU. This keeps private V8
// tests out of Node's internal fixture/header configuration.
void NodeStartupSetUpV8PrivateCase();
void NodeStartupTearDownV8PrivateCase();
node::ArrayBufferAllocator* NodeStartupV8PrivateAllocator();
uv_loop_t* NodeStartupV8PrivateLoop();
node::MultiIsolatePlatform* NodeStartupV8PrivatePlatform();

class V8PrivateStartupTestFixture : public ::testing::Test {
 protected:
  void SetUp() override { NodeStartupSetUpV8PrivateCase(); }

  void TearDown() override {
    if (isolate_ != nullptr) {
      NodeStartupV8PrivatePlatform()->DrainTasks(isolate_);
      NodeStartupV8PrivatePlatform()->DisposeIsolate(isolate_);
      isolate_ = nullptr;
    }
    NodeStartupTearDownV8PrivateCase();
  }

  v8::Isolate* NewTestIsolate(const node::IsolateSettings& settings = {}) {
    isolate_ = node::NewIsolate(
        NodeStartupV8PrivateAllocator(), NodeStartupV8PrivateLoop(),
        NodeStartupV8PrivatePlatform(), nullptr, settings);
    return isolate_;
  }

  void DisposeTestIsolate() {
    if (isolate_ == nullptr) return;
    NodeStartupV8PrivatePlatform()->DrainTasks(isolate_);
    NodeStartupV8PrivatePlatform()->DisposeIsolate(isolate_);
    isolate_ = nullptr;
  }

  v8::Isolate* isolate_ = nullptr;
};

#endif  // TEST_CCTEST_V8_PRIVATE_STARTUP_TEST_FIXTURE_H_
