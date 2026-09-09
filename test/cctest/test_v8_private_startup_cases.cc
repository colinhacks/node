#include "node_test_fixture.h"

namespace {

class NodeStartupBridgeFixture final : public NodeZeroIsolateTestFixture {
 public:
  static void SetUpPrivateCase() {
    SetUpTestCase();
    NodeStartupBridgeFixture fixture;
    fixture.SetUp();
  }

  static void TearDownPrivateCase() {
    allocator.reset();
    TearDownTestCase();
  }

  static node::ArrayBufferAllocator* allocator_for_private_case() {
    return allocator.get();
  }

  static uv_loop_t* loop_for_private_case() { return &current_loop; }

  static node::MultiIsolatePlatform* platform_for_private_case() {
    return platform.get();
  }

 protected:
  // This bridge is instantiated only to reuse NodeZero's allocator setup; it
  // is not itself registered as a gtest case.
  void TestBody() override {}
};

}  // namespace

void NodeStartupSetUpV8PrivateCase() {
  NodeStartupBridgeFixture::SetUpPrivateCase();
}

void NodeStartupTearDownV8PrivateCase() {
  NodeStartupBridgeFixture::TearDownPrivateCase();
}

node::ArrayBufferAllocator* NodeStartupV8PrivateAllocator() {
  return NodeStartupBridgeFixture::allocator_for_private_case();
}

uv_loop_t* NodeStartupV8PrivateLoop() {
  return NodeStartupBridgeFixture::loop_for_private_case();
}

node::MultiIsolatePlatform* NodeStartupV8PrivatePlatform() {
  return NodeStartupBridgeFixture::platform_for_private_case();
}

void NodeStartupSourcePositionTestsAnchor();
void NodeStartupAdvancedSourcePositionTestsAnchor();

namespace {

// These calls retain the V8-configured archive objects that own the gtest
// registrations; a static archive would otherwise drop unreferenced tests.
class V8PrivateCctestAnchors {
 public:
  V8PrivateCctestAnchors() {
    NodeStartupSourcePositionTestsAnchor();
    NodeStartupAdvancedSourcePositionTestsAnchor();
  }
};

V8PrivateCctestAnchors v8_private_cctest_anchors;

}  // namespace
