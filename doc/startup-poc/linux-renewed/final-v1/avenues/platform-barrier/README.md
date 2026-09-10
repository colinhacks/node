# Platform worker ready barrier

## Candidate

`platform-worker-ready-barrier.patch` removes the constructor-only mutex, condition variable, pending-worker count, and worker-side signal from `WorkerThreadsTaskRunner` in `src/node_platform.cc`. It retains the delayed-task scheduler readiness semaphore. The scheduler must initialize `uv_loop_t` and `uv_async_t` before `PostDelayedTask()` can call `uv_async_send()`.

The ordinary worker queue exists before any `uv_thread_create()` call. A worker only retains the queue pointer, identifier, and debug level after its entry routine begins. `TaskQueue` serializes push/pop/stop operations, and `Shutdown()` stops the queue, stops the delayed scheduler, then joins every created thread before the runner or its queue can be destroyed.

The patch also declares `WorkerThreadsTaskRunner`'s destructor in `src/node_platform.h` and defaults it out of line after `DelayedTaskScheduler` is complete. This preserves the implicit destructor's behavior while allowing the additive cctest to instantiate the runner on the stack without requiring the private scheduler definition in the header.

The candidate does not reduce the worker count or defer pool creation. Linux trace evidence supplied for this experiment shows an empty launch already posts optimizing, baseline, and Maglev jobs, an immediate MemoryPool release task, and an eight-second delayed follow-up. Lazy-pool variants therefore change real scheduled work rather than removing unused startup work.

## Additive cctest

`test_platform_worker_start.cc` is the source for the new `test/cctest/test_platform_worker_start.cc`. Node's `configure.py` collects every `.cc` and `.h` under `test/cctest`, so the patch requires no build-manifest edit. The tests cover immediate user-blocking work plus `BlockingDrain()`, shutdown without a posted task, and eight construction/shutdown cycles. They also pin the existing `NumberOfWorkerThreads()` result for a one-worker runner at two because `threads_` contains the delayed scheduler and the platform worker.

`REVIEW.md` records the source-backed lifetime analysis, risks, and static verification result.

## Scope and non-goals

- No source worktree, VM, build output, or GitHub state was modified.
- No startup-time result is claimed. The candidate requires a native Linux build and test run before performance or correctness claims.
- No delayed-task ordering, scheduler readiness, worker-pool size, or `NumberOfWorkerThreads()` behavior changes.
- The existing partial-creation branch remains intentionally narrow. Removing the wait means it no longer waits forever for a worker that was never created, but it does not add recovery for a runner that has no platform worker capable of consuming work.
