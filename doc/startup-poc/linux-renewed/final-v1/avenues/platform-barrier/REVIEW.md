# Barrier removal review

## Baseline

The source review is pinned to [`colinhacks/node` commit `f788616c`](https://github.com/colinhacks/node/tree/f788616cf1515e30a8cce13513dbe8b30e567904). It does not report a build or runtime result.

## Source evidence

| Concern | Evidence | Result |
| --- | --- | --- |
| Barrier ownership | [`src/node_platform.cc:20-26`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/src/node_platform.cc#L20-L26) puts the mutex, condition variable, and count pointers only in `PlatformWorkerData`; [`src/node_platform.cc:243-278`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/src/node_platform.cc#L243-L278) creates those objects on the constructor stack and waits for the count. | Removing those fields and the wait does not remove shared runtime state. |
| Worker lifetime | [`src/node_platform.cc:51-85`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/src/node_platform.cc#L51-L85) transfers `PlatformWorkerData` ownership to the worker, copies the task-queue pointer, then blocks on the queue. [`src/node_platform.cc:301-307`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/src/node_platform.cc#L301-L307) stops both queues and joins every thread. | `pending_worker_tasks_` remains live until all worker entry points have returned. |
| Ordinary work synchronization | [`src/node_platform.cc:778-803`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/src/node_platform.cc#L778-L803) locks task pushes and blocking pops; [`src/node_platform.cc:820-823`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/src/node_platform.cc#L820-L823) wakes blocked workers during shutdown. | A caller may post immediate work as soon as the runner constructor returns. A worker can consume it after completing its unchanged thread-name and trace-metadata setup. |
| Delayed work readiness | [`src/node_platform.cc:102-110`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/src/node_platform.cc#L102-L110) waits for the delayed scheduler, and [`src/node_platform.cc:143-151`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/src/node_platform.cc#L143-L151) initializes its loop and `uv_async_t` before posting readiness. | The patch leaves this semaphore unchanged because `PostDelayedTask()` sends that async handle. |
| Tracing and global-platform order | [`src/node_platform.cc:457-474`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/src/node_platform.cc#L457-L474) sets the tracing controller before constructing the runner. [`src/node_v8_platform-inl.h:25-31`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/src/node_v8_platform-inl.h#L25-L31) initializes tracing before constructing `NodePlatform`. | The worker still emits its metadata after tracing is initialized. The candidate only overlaps later bootstrap with that unchanged worker setup. |
| Embedding | [`src/api/environment.cc:752-759`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/src/api/environment.cc#L752-L759) creates `NodePlatform` through `MultiIsolatePlatform::Create()`. | The same constructor path is covered by the lifetime review; an embedder gate remains in `TEST-PLAN.md`. |
| Worker-count contract | [`src/node_platform.cc:309-310`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/src/node_platform.cc#L309-L310) returns `threads_.size()`, and [`src/node_platform.cc:252-270`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/src/node_platform.cc#L252-L270) stores the scheduler plus each successfully created worker there. | The candidate preserves the observable count, including the scheduler entry. |
| cctest discovery | [`configure.py:1901-1904`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/configure.py#L1901-L1904) recursively collects cctest `.cc` and `.h` files. | The added test requires no build-file change. |

The native cctest compilation exposed an incomplete-type error from the original implicit inline destructor: the public runner holds `std::unique_ptr<DelayedTaskScheduler>`, while `DelayedTaskScheduler` is defined only in `src/node_platform.cc`. The candidate declares the destructor in `src/node_platform.h` and defaults it after that nested class definition. This keeps its public visibility and default destruction behavior without exposing the private scheduler implementation.

## Risks and limits

- `uv_thread_create()` failure is not injected by the cctest. The old constructor waits for the requested count even after breaking out of creation. This candidate removes that wait, so it removes the hang, but a runner with zero successful platform workers still cannot execute queued work. No recovery policy is added.
- The candidate does not guarantee that an immediate task runs before later bootstrap. It guarantees only that the task queue is ready for a worker and that `BlockingDrain()` observes a user-blocking task after it completes.
- The delayed scheduler remains a construction barrier. Removing it would permit `uv_async_send()` against an uninitialized handle.
- No lazy-pool alternative is included. The supplied Linux trace records immediate V8 optimizing, baseline, and Maglev jobs, an immediate MemoryPool release task, and a delayed follow-up. A lazy pool would change execution timing for real work rather than eliminate idle startup work.
- No performance measurement has been run. The patch is a concurrency/lifetime candidate, not evidence of an improvement.

## Static verification

`git apply --check --whitespace=error-all platform-worker-ready-barrier.patch` validated the copied patch against the pinned checkout. A native Linux build was not run. [`TEST-PLAN.md`](TEST-PLAN.md) lists the focused cctest and broader gates.
