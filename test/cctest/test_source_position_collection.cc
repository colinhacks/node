#include <array>
#include <memory>
#include <string>
#include "gtest/gtest.h"
#include "src/api/api-inl.h"
#include "src/codegen/compilation-cache.h"
#include "src/execution/isolate.h"
#include "src/objects/js-function-inl.h"
#include "src/objects/shared-function-info-inl.h"
#include "v8-profiler.h"
#include "v8-script.h"
#include "v8_private_startup_test_fixture.h"
namespace {
v8::Local<v8::String> V8String(v8::Isolate* isolate, const char* value) {
  return v8::String::NewFromUtf8(isolate, value).ToLocalChecked();
}
v8::Local<v8::Function> GetGlobalFunction(v8::Isolate* isolate,
                                          v8::Local<v8::Context> context,
                                          const char* name) {
  v8::Local<v8::Value> value =
      context->Global()->Get(context, V8String(isolate, name)).ToLocalChecked();
  CHECK(value->IsFunction());
  return value.As<v8::Function>();
}

bool CanCollectSourcePositions(v8::Isolate* isolate,
                               v8::Local<v8::Function> function) {
  auto* internal_isolate = reinterpret_cast<v8::internal::Isolate*>(isolate);
  auto internal_function = v8::internal::Cast<v8::internal::JSFunction>(
      v8::Utils::OpenHandle(*function));
  return internal_function->shared()->CanCollectSourcePosition(
      internal_isolate);
}

bool HasSourcePositionTable(v8::Isolate* isolate,
                            v8::Local<v8::Function> function) {
  auto* internal_isolate = reinterpret_cast<v8::internal::Isolate*>(isolate);
  auto internal_function = v8::internal::Cast<v8::internal::JSFunction>(
      v8::Utils::OpenHandle(*function));
  auto shared = internal_function->shared();
  return shared->HasBytecodeArray() &&
         shared->GetBytecodeArray(internal_isolate)->HasSourcePositionTable();
}
void ExpectValue(v8::Isolate* isolate,
                 v8::Local<v8::Context> context,
                 v8::Local<v8::Function> function,
                 int expected) {
  v8::Local<v8::Value> argument = v8::Integer::New(isolate, expected - 1);
  v8::Local<v8::Value> result;
  ASSERT_TRUE(function->Call(context, v8::Undefined(isolate), 1, &argument)
                  .ToLocal(&result));
  EXPECT_EQ(expected, result->Int32Value(context).FromJust());
}
void ExpectDetailedStack(v8::Isolate* isolate,
                         v8::Local<v8::Context> context,
                         v8::Local<v8::Function> function,
                         const char* resource_name,
                         int expected_line) {
  v8::TryCatch try_catch(isolate);
  v8::Local<v8::Value> argument = v8::Undefined(isolate);
  v8::Local<v8::Value> result;
  ASSERT_FALSE(function->Call(context, v8::Undefined(isolate), 1, &argument)
                   .ToLocal(&result));
  ASSERT_TRUE(try_catch.HasCaught());
  v8::Local<v8::Message> message = try_catch.Message();
  ASSERT_FALSE(message.IsEmpty());
  EXPECT_EQ(expected_line, message->GetLineNumber(context).FromJust());
  v8::String::Utf8Value actual_resource(
      isolate, message->GetScriptOrigin().ResourceName());
  ASSERT_NE(nullptr, *actual_resource);
  EXPECT_EQ(resource_name, std::string(*actual_resource));
  v8::Local<v8::Value> stack;
  ASSERT_TRUE(try_catch.Exception()
                  .As<v8::Object>()
                  ->Get(context, V8String(isolate, "stack"))
                  .ToLocal(&stack));
  ASSERT_TRUE(stack->IsString());
  v8::String::Utf8Value stack_text(isolate, stack);
  ASSERT_NE(nullptr, *stack_text);
  EXPECT_NE(std::string::npos, std::string(*stack_text).find(resource_name));
}
class SourcePositionCollectionTest : public V8PrivateStartupTestFixture {
 protected:
  void SetUp() override {
    V8PrivateStartupTestFixture::SetUp();
    node::IsolateSettings settings;
    // Deliberately omit Node's default detailed-position flag. This must stay
    // before all test-script compilation so CpuProfiler below collects the
    // previously compiled bytecode arrays through the public one-way API.
    settings.flags = node::MESSAGE_LISTENER_WITH_ERROR_LEVEL |
        node::SHOULD_NOT_SET_PREPARE_STACK_TRACE_CALLBACK;
    isolate_ = NewTestIsolate(settings);
    ASSERT_NE(nullptr, isolate_);
    isolate_->Enter();
  }
  void TearDown() override {
    if (isolate_ != nullptr) {
      isolate_->Exit();
    }
    V8PrivateStartupTestFixture::TearDown();
  }
};
TEST_F(SourcePositionCollectionTest,
       CollectsCompiledScriptEvalFunctionAndConsumedCache) {
  v8::HandleScope handle_scope(isolate_);
  v8::Local<v8::Context> context = v8::Context::New(isolate_);
  v8::Context::Scope context_scope(context);
  v8::Local<v8::Value> error_value;
  ASSERT_TRUE(context->Global()
                  ->Get(context, V8String(isolate_, "Error"))
                  .ToLocal(&error_value));
  ASSERT_TRUE(error_value.As<v8::Object>()
                  ->Set(context, V8String(isolate_, "stackTraceLimit"),
                        v8::Integer::New(isolate_, 10))
                  .FromMaybe(false));
  auto* internal_isolate = reinterpret_cast<v8::internal::Isolate*>(isolate_);
  int stack_trace_limit;
  ASSERT_TRUE(internal_isolate->GetStackTraceLimit(
      internal_isolate, &stack_trace_limit));
  ASSERT_EQ(10, stack_trace_limit);
  const char* source =
      "function ordinaryControl(value) {\n"
      "  if (value === undefined) {\n"
      "    throw new Error('ordinary sentinel');\n"
      "  }\n"
      "  return value + 1;\n"
      "}\n"
      "eval(\"globalThis.evalControl = function evalControl(value) {\\n\"\n"
      "  + \"  if (value === undefined) {\\n\"\n"
      "  + \"    throw new Error('eval sentinel');\\n\"\n"
      "  + \"  }\\n\"\n"
      "  + \"  return value + 1;\\n\"\n"
      "  + \"}\\n//# sourceURL=cctest-source-position-eval.js\");\n"
      "globalThis.functionControl = Function(\n"
      "  \"return function functionControl(value) {\\n\" +\n"
      "  \"  if (value === undefined) {\\n\" +\n"
      "  \"    throw new Error('Function sentinel');\\n\" +\n"
      "  \"  }\\n\" +\n"
      "  \"  return value + 1;\\n\" +\n"
      "  \"}\\n//# sourceURL=cctest-source-position-function.js\"\n"
      ")();\n";
  v8::ScriptOrigin ordinary_origin(
      V8String(isolate_, "cctest-source-position-ordinary.js"));
  v8::ScriptCompiler::Source ordinary_source(V8String(isolate_, source),
                                             ordinary_origin);
  v8::Local<v8::Script> ordinary_script =
      v8::ScriptCompiler::Compile(
          context, &ordinary_source, v8::ScriptCompiler::kEagerCompile)
          .ToLocalChecked();
  ASSERT_FALSE(ordinary_script->Run(context).IsEmpty());
  const char* cache_source =
      "globalThis.cachedControl = function cachedControl(value) {\n"
      "  if (value === undefined) {\n"
      "    throw new Error('cache sentinel');\n"
      "  }\n"
      "  return value + 1;\n"
      "};\n";
  v8::ScriptOrigin cache_origin(
      V8String(isolate_, "cctest-source-position-cache.js"));
  v8::ScriptCompiler::Source cache_producer_source(
      V8String(isolate_, cache_source), cache_origin);
  v8::Local<v8::Script> cache_producer =
      v8::ScriptCompiler::Compile(
          context, &cache_producer_source, v8::ScriptCompiler::kEagerCompile)
          .ToLocalChecked();
  ASSERT_FALSE(cache_producer->Run(context).IsEmpty());
  std::unique_ptr<v8::ScriptCompiler::CachedData> cached_data(
      v8::ScriptCompiler::CreateCodeCache(cache_producer->GetUnboundScript()));
  ASSERT_NE(nullptr, cached_data);
  // The compiler checks the in-memory cache before supplied cache data. Clear
  // it so the consumer must deserialize the supplied bytes rather than reuse
  // the producer's SFI.
  reinterpret_cast<v8::internal::Isolate*>(isolate_)
      ->compilation_cache()
      ->Clear();
  v8::ScriptCompiler::Source cache_consumer_source(
      V8String(isolate_, cache_source), cache_origin, cached_data.release());
  v8::Local<v8::Script> cache_consumer =
      v8::ScriptCompiler::Compile(context,
                                  &cache_consumer_source,
                                  v8::ScriptCompiler::kConsumeCodeCache)
          .ToLocalChecked();
  ASSERT_NE(nullptr, cache_consumer_source.GetCachedData());
  ASSERT_FALSE(cache_consumer_source.GetCachedData()->rejected);
  EXPECT_EQ(
      v8::ScriptCompiler::InMemoryCacheResult::kMiss,
      cache_consumer_source.GetCompilationDetails().in_memory_cache_result);
  ASSERT_FALSE(cache_consumer->Run(context).IsEmpty());
  v8::Local<v8::Function> ordinary =
      GetGlobalFunction(isolate_, context, "ordinaryControl");
  v8::Local<v8::Function> evaluated =
      GetGlobalFunction(isolate_, context, "evalControl");
  v8::Local<v8::Function> constructed =
      GetGlobalFunction(isolate_, context, "functionControl");
  v8::Local<v8::Function> cached =
      GetGlobalFunction(isolate_, context, "cachedControl");
  ExpectValue(isolate_, context, ordinary, 1);
  ExpectValue(isolate_, context, evaluated, 2);
  ExpectValue(isolate_, context, constructed, 3);
  ExpectValue(isolate_, context, cached, 4);
  const std::array<v8::Local<v8::Function>, 4> functions = {
      ordinary, evaluated, constructed, cached};
  size_t eligible_before_enable = 0;
  for (v8::Local<v8::Function> function : functions) {
    eligible_before_enable += CanCollectSourcePositions(isolate_, function);
  }
  // Function-constructor bytecode can already carry positions by design, but
  // this proves that the current collector has real pre-existing work. Merely
  // reading Error.stack after enable cannot establish that property.
  ASSERT_GT(eligible_before_enable, 0u);
  // This is the same public API Node calls during isolate setup. It must
  // collect the four compiled-and-executed bodies above rather than relying
  // on an internal test-only toggle or on fresh compilation after enable.
  v8::CpuProfiler::UseDetailedSourcePositionsForProfiling(isolate_);
  for (v8::Local<v8::Function> function : functions) {
    EXPECT_FALSE(CanCollectSourcePositions(isolate_, function));
    EXPECT_TRUE(HasSourcePositionTable(isolate_, function));
  }
  ExpectDetailedStack(
      isolate_, context, ordinary, "cctest-source-position-ordinary.js", 3);
  ExpectDetailedStack(
      isolate_, context, evaluated, "cctest-source-position-eval.js", 3);
  ExpectDetailedStack(
      isolate_, context, constructed, "cctest-source-position-function.js", 5);
  ExpectDetailedStack(
      isolate_, context, cached, "cctest-source-position-cache.js", 3);
}
}  // namespace

void NodeStartupSourcePositionTestsAnchor() {}
