#include <cstring>
#include <memory>

#include "v8_private_startup_test_fixture.h"
#include "v8-profiler.h"
#include "v8-script.h"

#include "src/api/api-inl.h"
#include "src/debug/liveedit.h"
#include "src/execution/isolate.h"
#include "src/heap/factory.h"
#include "src/objects/bytecode-array-inl.h"
#include "src/objects/js-function-inl.h"
#include "src/objects/objects-inl.h"
#include "src/objects/shared-function-info-inl.h"

namespace {

class ChunkSourceStream final
    : public v8::ScriptCompiler::ExternalSourceStream {
 public:
  explicit ChunkSourceStream(const char* const* chunks) : chunks_(chunks) {}

  size_t GetMoreData(const uint8_t** src) override {
    const char* chunk = chunks_[index_++];
    if (chunk == nullptr) return 0;
    size_t size = std::strlen(chunk);
    uint8_t* copy = new uint8_t[size];
    std::memcpy(copy, chunk, size);
    *src = copy;
    return size;
  }

 private:
  const char* const* chunks_;
  size_t index_ = 0;
};

void RunStreamingTask(void* arg) {
  static_cast<v8::ScriptCompiler::ScriptStreamingTask*>(arg)->Run();
}

v8::Local<v8::String> String(v8::Isolate* isolate, const char* value) {
  return v8::String::NewFromUtf8(isolate, value).ToLocalChecked();
}

v8::internal::DirectHandle<v8::internal::SharedFunctionInfo>
SharedInfo(v8::Local<v8::UnboundScript> script) {
  return v8::internal::Cast<v8::internal::SharedFunctionInfo>(
      v8::Utils::OpenDirectHandle(*script));
}

v8::internal::DirectHandle<v8::internal::SharedFunctionInfo>
SharedInfo(v8::internal::Isolate* isolate, v8::Local<v8::Function> function) {
  auto internal_function = v8::internal::Cast<v8::internal::JSFunction>(
      v8::Utils::OpenDirectHandle(*function));
  return v8::internal::DirectHandle<v8::internal::SharedFunctionInfo>(
      internal_function->shared(), isolate);
}

bool HasSourcePositionTable(
    v8::internal::Isolate* isolate,
    v8::internal::DirectHandle<v8::internal::SharedFunctionInfo> shared) {
  return shared->HasBytecodeArray() &&
         shared->GetBytecodeArray(isolate)->HasSourcePositionTable();
}

class SourcePositionsAdvancedTest : public V8PrivateStartupTestFixture {};

TEST_F(SourcePositionsAdvancedTest,
       StreamingPublishedFunctionIsCollectedAfterForegroundCompile) {
  v8::Isolate* isolate = NewTestIsolate();
  ASSERT_NE(nullptr, isolate);
  {
    v8::Isolate::Scope isolate_scope(isolate);
    v8::HandleScope handle_scope(isolate);
    auto* i_isolate = reinterpret_cast<v8::internal::Isolate*>(isolate);
    i_isolate->SetDetailedSourcePositionsForProfiling(false);
    ASSERT_FALSE(i_isolate->detailed_source_positions_for_profiling());

    v8::Local<v8::Context> context = node::NewContext(isolate);
    ASSERT_FALSE(context.IsEmpty());
    v8::Context::Scope context_scope(context);

    // The sentinel terminates ChunkSourceStream. No V8 test-only helper is
    // linked into Node's cctest target.
    const char* chunks[] = {"function streamed() { return 1; }\n", nullptr};
    v8::ScriptCompiler::StreamedSource source(
        std::make_unique<ChunkSourceStream>(chunks),
        v8::ScriptCompiler::StreamedSource::ONE_BYTE);
    std::unique_ptr<v8::ScriptCompiler::ScriptStreamingTask> task(
        v8::ScriptCompiler::StartStreaming(isolate, &source));
    ASSERT_NE(task, nullptr);
    uv_thread_t thread;
    ASSERT_EQ(uv_thread_create(&thread, RunStreamingTask, task.get()), 0);
    ASSERT_EQ(uv_thread_join(&thread), 0);

    v8::ScriptOrigin origin(String(isolate, "streamed-positions.js"));
    v8::Local<v8::Script> script =
        v8::ScriptCompiler::Compile(
            context, &source, String(isolate, chunks[0]), origin)
            .ToLocalChecked();
    ASSERT_FALSE(script->Run(context).IsEmpty());
    v8::Local<v8::Value> streamed_value;
    ASSERT_TRUE(context->Global()
                    ->Get(context, String(isolate, "streamed"))
                    .ToLocal(&streamed_value));
    ASSERT_TRUE(streamed_value->IsFunction());
    v8::Local<v8::Function> streamed = streamed_value.As<v8::Function>();
    ASSERT_FALSE(streamed->Call(context, v8::Undefined(isolate), 0, nullptr)
                     .IsEmpty());
    auto shared = SharedInfo(i_isolate, streamed);
    ASSERT_TRUE(shared->HasBytecodeArray());
    ASSERT_TRUE(shared->CanCollectSourcePosition(i_isolate));

    // The completed streaming script and its executed function are published
    // on the foreground script list before detailed positions are requested.
    // This makes the public profiler call exercise the collector rather than
    // the finalizer's direct reparse of an unfinalized script.
    v8::CpuProfiler::UseDetailedSourcePositionsForProfiling(isolate);
    ASSERT_TRUE(i_isolate->detailed_source_positions_for_profiling());
    ASSERT_FALSE(shared->CanCollectSourcePosition(i_isolate));
    ASSERT_TRUE(HasSourcePositionTable(i_isolate, shared));
  }
}

TEST_F(SourcePositionsAdvancedTest,
       LiveEditRetainedFunctionKeepsDetailedSourcePositionTable) {
  v8::Isolate* isolate = NewTestIsolate();
  ASSERT_NE(nullptr, isolate);
  {
    v8::Isolate::Scope isolate_scope(isolate);
    v8::HandleScope handle_scope(isolate);
    auto* i_isolate = reinterpret_cast<v8::internal::Isolate*>(isolate);
    i_isolate->SetDetailedSourcePositionsForProfiling(false);
    ASSERT_FALSE(i_isolate->detailed_source_positions_for_profiling());

    v8::Local<v8::Context> context = node::NewContext(isolate);
    ASSERT_FALSE(context.IsEmpty());
    v8::Context::Scope context_scope(context);

    const char* old_source =
        "function retained() { return 1; }\n"
        "retained;\n";
    const char* new_source =
        "\n"
        "\n"
        "function retained() { return 2; }\n"
        "retained;\n";
    v8::ScriptOrigin origin(String(isolate, "live-edit-positions.js"));
    v8::Local<v8::Script> script =
        v8::Script::Compile(context, String(isolate, old_source), &origin)
            .ToLocalChecked();
    v8::Local<v8::Function> retained =
        script->Run(context).ToLocalChecked().As<v8::Function>();
    retained->Call(context, context->Global(), 0, nullptr).ToLocalChecked();

    auto old_shared = SharedInfo(i_isolate, retained);
    ASSERT_TRUE(old_shared->HasBytecodeArray());
    ASSERT_FALSE(HasSourcePositionTable(i_isolate, old_shared));
    const int start_position_before = old_shared->StartPosition();

    v8::CpuProfiler::UseDetailedSourcePositionsForProfiling(isolate);
    ASSERT_TRUE(i_isolate->detailed_source_positions_for_profiling());
    ASSERT_TRUE(HasSourcePositionTable(i_isolate, old_shared));

    v8::internal::Handle<v8::internal::Script> i_script(
        v8::internal::Cast<v8::internal::Script>(old_shared->script()),
        i_isolate);
    v8::debug::LiveEditResult result;
    v8::internal::LiveEdit::PatchScript(
        i_isolate,
        i_script,
        i_isolate->factory()->NewStringFromAsciiChecked(new_source),
        false,
        false,
        &result);
    ASSERT_EQ(result.status, v8::debug::LiveEditResult::OK);
    auto updated_shared = SharedInfo(i_isolate, retained);
    ASSERT_NE(old_shared->address(), updated_shared->address());
    EXPECT_EQ(updated_shared->StartPosition(), start_position_before + 2);
    EXPECT_TRUE(HasSourcePositionTable(i_isolate, old_shared));
    EXPECT_TRUE(updated_shared->HasBytecodeArray());
    EXPECT_TRUE(HasSourcePositionTable(i_isolate, updated_shared));
    ASSERT_EQ(retained->Call(context, context->Global(), 0, nullptr)
                  .ToLocalChecked()
                  ->Int32Value(context)
                  .FromJust(),
              2);
  }
}

TEST_F(SourcePositionsAdvancedTest,
       LiveEditLateCollectionCoversRetainedOldAndReplacementSfis) {
  v8::Isolate* isolate = NewTestIsolate();
  ASSERT_NE(nullptr, isolate);
  {
    v8::Isolate::Scope isolate_scope(isolate);
    v8::HandleScope handle_scope(isolate);
    auto* i_isolate = reinterpret_cast<v8::internal::Isolate*>(isolate);
    i_isolate->SetDetailedSourcePositionsForProfiling(false);
    ASSERT_FALSE(i_isolate->detailed_source_positions_for_profiling());

    v8::Local<v8::Context> context = node::NewContext(isolate);
    ASSERT_FALSE(context.IsEmpty());
    v8::Context::Scope context_scope(context);

    const char* old_source =
        "function retainedLate() { return 1; }\n"
        "retainedLate;\n";
    const char* new_source =
        "\n"
        "\n"
        "function retainedLate() { return 2; }\n"
        "retainedLate;\n";
    v8::ScriptOrigin origin(String(isolate, "live-edit-late-positions.js"));
    v8::Local<v8::Script> script =
        v8::Script::Compile(context, String(isolate, old_source), &origin)
            .ToLocalChecked();
    v8::Local<v8::Function> retained =
        script->Run(context).ToLocalChecked().As<v8::Function>();
    retained->Call(context, context->Global(), 0, nullptr).ToLocalChecked();
    v8::Global<v8::Function> retained_global(isolate, retained);

    // LiveEdit replaces this compiled SFI. Keep the old SFI alive across the
    // edit while the retained closure is updated to the replacement.
    auto old_shared = SharedInfo(i_isolate, retained);
    ASSERT_TRUE(old_shared->HasBytecodeArray());
    ASSERT_TRUE(old_shared->CanCollectSourcePosition(i_isolate));
    ASSERT_FALSE(HasSourcePositionTable(i_isolate, old_shared));
    v8::internal::Handle<v8::internal::SharedFunctionInfo>
        retained_old_shared(*old_shared, i_isolate);
    v8::internal::Handle<v8::internal::Script> i_script(
        v8::internal::Cast<v8::internal::Script>(
            retained_old_shared->script()),
        i_isolate);
    v8::debug::LiveEditResult result;
    v8::internal::LiveEdit::PatchScript(
        i_isolate,
        i_script,
        i_isolate->factory()->NewStringFromAsciiChecked(new_source),
        false,
        false,
        &result);
    ASSERT_EQ(result.status, v8::debug::LiveEditResult::OK);

    v8::Local<v8::Function> updated = retained_global.Get(isolate);
    auto updated_shared = SharedInfo(i_isolate, updated);
    ASSERT_NE(retained_old_shared->address(), updated_shared->address());
    ASSERT_TRUE(updated_shared->HasBytecodeArray());
    ASSERT_TRUE(retained_old_shared->CanCollectSourcePosition(i_isolate));
    ASSERT_TRUE(updated_shared->CanCollectSourcePosition(i_isolate));
    ASSERT_FALSE(retained_old_shared->GetBytecodeArray(i_isolate)
                     ->HasSourcePositionTable());
    ASSERT_FALSE(HasSourcePositionTable(i_isolate, updated_shared));

    // Request detailed positions only after LiveEdit has kept the old SFI and
    // published its replacement. Both live bytecode arrays must be collected.
    v8::CpuProfiler::UseDetailedSourcePositionsForProfiling(isolate);
    ASSERT_TRUE(i_isolate->detailed_source_positions_for_profiling());
    EXPECT_FALSE(retained_old_shared->CanCollectSourcePosition(i_isolate));
    EXPECT_FALSE(updated_shared->CanCollectSourcePosition(i_isolate));
    EXPECT_TRUE(retained_old_shared->GetBytecodeArray(i_isolate)
                    ->HasSourcePositionTable());
    EXPECT_TRUE(HasSourcePositionTable(i_isolate, updated_shared));
    ASSERT_EQ(updated->Call(context, context->Global(), 0, nullptr)
                  .ToLocalChecked()
                  ->Int32Value(context)
                  .FromJust(),
              2);
  }
}

}  // namespace

void NodeStartupAdvancedSourcePositionTestsAnchor() {}
