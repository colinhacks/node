#include <atomic>
#include <memory>

#include "gtest/gtest.h"
#include "node_platform.h"

namespace {

class IncrementTask final : public v8::Task {
 public:
  explicit IncrementTask(std::atomic<int>* count) : count_(count) {}

  void Run() override { count_->fetch_add(1, std::memory_order_relaxed); }

 private:
  std::atomic<int>* count_;
};

TEST(PlatformWorkerStartTest, RunsImmediateUserBlockingWork) {
  std::atomic<int> run_count = 0;
  node::WorkerThreadsTaskRunner runner(
      1, node::PlatformDebugLogLevel::kNone);

  // The delayed-task scheduler occupies one entry in the existing vector.
  EXPECT_EQ(2, runner.NumberOfWorkerThreads());
  runner.PostTask(v8::TaskPriority::kUserBlocking,
                  std::make_unique<IncrementTask>(&run_count),
                  v8::SourceLocation::Current());
  runner.BlockingDrain();
  EXPECT_EQ(1, run_count.load(std::memory_order_relaxed));
  runner.Shutdown();
}

TEST(PlatformWorkerStartTest, ShutsDownWithoutPostedWork) {
  node::WorkerThreadsTaskRunner runner(
      1, node::PlatformDebugLogLevel::kNone);
  runner.Shutdown();
}

TEST(PlatformWorkerStartTest, RepeatedConstructionAndShutdown) {
  for (int i = 0; i < 8; i++) {
    node::WorkerThreadsTaskRunner runner(
        1, node::PlatformDebugLogLevel::kNone);
    EXPECT_EQ(2, runner.NumberOfWorkerThreads());
    runner.Shutdown();
  }
}

}  // namespace
