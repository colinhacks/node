# Native test plan

## Patch application

Apply the candidate to a clean worktree at `907b36afd7f9faeb3a42a6d9d9320edd59b208f1`:

```sh
git apply --check platform-worker-ready-barrier.patch
git apply platform-worker-ready-barrier.patch
```

The public-startup worktree is not clean because its workflow file is independently modified. Check the three candidate paths rather than treating that unrelated file as part of this candidate.

## Current status

The first native attempt built `src/node_platform.cc` but failed while compiling the additive cctest. The implicit inline destructor of `WorkerThreadsTaskRunner` instantiated deletion of its incomplete `DelayedTaskScheduler` member. The revised patch declares the destructor in the header and defaults it after the private nested class definition. The native build and tests must be rerun; static patch application alone does not validate this C++ change.

## Native Linux gate

Configure and build cctest in a fresh Linux build directory, then run only the new suite first:

```sh
./configure
make -j8 cctest
out/Release/cctest --gtest_filter=PlatformWorkerStartTest.*
```

Run the full cctest target and the existing platform/task suites after the focused gate:

```sh
out/Release/cctest
out/Release/cctest --gtest_filter='PlatformTest.*:TaskQueueTest.*'
```

## Required review points

- Verify every worker executes the thread-name and trace-metadata calls before entering `TaskQueue::BlockingPop()`. The patch does not move or remove either call.
- Verify the runner outlives every worker. `Shutdown()` must stop the queue and delayed scheduler, then join `threads_`; do not destroy a `NodePlatform` while callers can still post tasks.
- Verify an embedding path that calls `MultiIsolatePlatform::Create()` and the regular Node initialization path. Both create `NodePlatform`, which sets the tracing controller before constructing `WorkerThreadsTaskRunner`.
- Verify the selected build's `NumberOfWorkerThreads()` contract. The current method returns `threads_.size()`, including `DelayedTaskScheduler`; the candidate preserves that value.
- Exercise constrained resources if feasible. A failed `uv_thread_create()` no longer leaves the constructor waiting for the requested count, but a zero-worker runner still cannot execute queued platform work. This is a pre-existing failure-mode boundary, not a recovery change.

## Performance protocol

Measure only after the correctness gates pass. Use matched Linux baseline/candidate builds, pinned CPU affinity and governor, warm-up rejection, randomized interleaving, and report distributions with raw samples. Trace an empty invocation on both builds to confirm the same worker-job and delayed-task categories remain. Do not present thread-count reduction or lazy-pool results as evidence for this candidate.
