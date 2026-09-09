#include "gtest/gtest.h"

#ifdef __APPLE__
#include <dlfcn.h>

TEST(PostmortemExportsTest, MetadataIsDynamicallyVisible) {
  const char* symbols[] = {
      "nodedbg_const_BaseObject__kInternalFieldCount__int",
      "nodedbg_const_ContextEmbedderIndex__kEnvironment__int",
      "nodedbg_const_HandleWrap__kInternalFieldCount__int",
      "nodedbg_const_ReqWrap__kInternalFieldCount__int",
      "nodedbg_offset_BaseObject__persistent_handle___v8_Persistent_v8_Object",
      "nodedbg_offset_Environment_HandleWrapQueue__head___ListNode_HandleWrap",
      "nodedbg_offset_Environment_ReqWrapQueue__head___ListNode_ReqWrapQueue",
      ("nodedbg_offset_Environment__handle_wrap_queue___"
       "Environment_HandleWrapQueue"),
      "nodedbg_offset_Environment__req_wrap_queue___Environment_ReqWrapQueue",
      "nodedbg_offset_ExternalString__data__uintptr_t",
      "nodedbg_offset_HandleWrap__handle_wrap_queue___ListNode_HandleWrap",
      "nodedbg_offset_ListNode_HandleWrap__next___uintptr_t",
      "nodedbg_offset_ListNode_HandleWrap__prev___uintptr_t",
      "nodedbg_offset_ListNode_ReqWrap__next___uintptr_t",
      "nodedbg_offset_ListNode_ReqWrap__prev___uintptr_t",
      "nodedbg_offset_ReqWrap__req_wrap_queue___ListNode_ReqWrapQueue",
  };

  for (const char* symbol : symbols) {
    EXPECT_NE(nullptr, dlsym(RTLD_DEFAULT, symbol)) << symbol;
  }
}
TEST(PublicExportsTest, EmbeddingApisAreDynamicallyVisible) {
  const char* symbols[] = {
      "_ZN4node12signo_stringEi",
      "_ZN4node20EmbedderSnapshotData19BuiltinSnapshotDataEv",
      "_ZNK4node20EmbedderSnapshotData18DeleteSnapshotDataclEPKS0_",
  };
  for (const char* symbol : symbols) {
    EXPECT_NE(nullptr, dlsym(RTLD_DEFAULT, symbol)) << symbol;
  }
}
#endif  // __APPLE__
