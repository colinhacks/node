# Adaptive pool timing results

## Decision

Close the adaptive or lazy initial-worker avenue. Do not start a delayed-scheduler prototype from this capture either. The five captures show small synchronous construction segments, but not recoverable end-to-end startup time.

The default four-worker constructor's median create-to-last-ready span is 138.120 microseconds. A lazy policy could relocate that segment from construction. It cannot eliminate it because every captured workload posts worker work after startup.

The delayed scheduler is distinct from the ordinary worker pool. Its default-empty ready duration is 174.236 microseconds at p50. It must not be added to the worker span: both run in the same constructor, and the data does not establish a combined wall-clock saving.

The current normal full-startup scale is about 18 milliseconds. The 75.662-microsecond median difference between the one-worker and default four-worker constructor is 0.42% of that scale. That ratio describes one instrumented constructor dimension. It is not a predicted startup improvement.

## Integrity

The input is archived Linux evidence. Its canonical tree digest is `f5ec7d30208e6a5be4d4f1b81f9503a8d36d38060b0370febbc85a19f01058e8`; see [`../ARCHIVED-EVIDENCE.md`](../ARCHIVED-EVIDENCE.md).

The digest is SHA-256 over sorted UTF-8 lines containing each input file's SHA-256, two spaces, its path relative to `platform-timing-v1`, and a line feed. The input contains 765 files and 1,720,150 bytes.

| Case | Case aggregate SHA-256 | Configured workers | Streams |
| --- | --- | ---: | ---: |
| Default empty | `290ade3020ecb02052f6e63380b5f3824755c152dc133ce6ef0b0b8d2f259ad7` | 4 | 50 |
| One-worker empty | `b0b1255e29cc79a2b922231ad7ae5cdf95cab604bbec98256c374b11851c5426` | 1 | 50 |
| Eight-worker empty | `556f0177b4f4992c2a5bfb8a2f6e3dbb83b32001bf6332bc6fd3dfa3af895522` | 8 | 50 |
| Default hello | `8fc0cab6380c46b1d4a029ed0d6c52fa247011eb86670b9228104aec52001f0e` | 4 | 50 |
| Default worker | `dea8e6e77a2c8723a77c2dcbc497ef00de21cfda55e4b52e950b58ce53ae4145` | 4 | 50 |

Every case completed 50 of 50 runs. All 250 raw streams re-parse under the strict version-1 collector and exactly match their saved records. Every stream has zero drops, successful worker creation equal to configured worker count, and a stable executable SHA-256 of `f656084f4ff5d7245d711210b8bbc2a98c8fb653b67451f9b673ed4541be92f0` before and after capture.

The scalar file [`ADAPTIVE-POOL-TIMING-SCALARS.json`](ADAPTIVE-POOL-TIMING-SCALARS.json) contains min, p05, p25, p50, p75, p95, and max values. It uses R-7 linear interpolation over 50 runs per case. All time values below are microseconds.

## Construction and posting

The platform records one delayed scheduler plus the configured worker pool. The scheduler is already ready before worker creation begins.

| Case | Constructor p50 / p95 | Delayed scheduler ready p50 / p95 | Worker create-to-last-ready p50 / p95 | First post after constructor p50 / p95 |
| --- | ---: | ---: | ---: | ---: |
| Default empty | 367.584 / 452.195 | 174.236 / 198.222 | 138.120 / 187.236 | 11,368.344 / 12,301.967 |
| One-worker empty | 291.922 / 356.708 | 184.339 / 214.530 | 64.099 / 97.353 | 11,134.404 / 11,872.536 |
| Eight-worker empty | 486.099 / 645.061 | 169.138 / 209.524 | 226.383 / 273.158 | 11,132.821 / 12,362.346 |
| Default hello | 359.077 / 445.348 | 173.357 / 202.244 | 137.780 / 170.753 | 11,124.958 / 12,354.321 |
| Default worker | 366.317 / 435.439 | 178.879 / 201.595 | 143.649 / 190.275 | 11,220.818 / 11,772.557 |

The first-post gap is about 11 milliseconds in every case. It is not recoverable worker-startup time. The capture shows only that the already-ready pool remains idle until later bootstrap work posts the first task.

The per-call worker creation intervals overlap with one another. Their sum is therefore not a wall-clock budget. The create-to-last-ready span is the relevant construction-phase span, and it is only a relocation candidate until a policy proves an end-to-end dependency can avoid it.

The one-worker and eight-worker flags modify the existing fixed-pool cardinality. They do not implement an adaptive policy. The observed constructor deltas are 75.662 microseconds from one to four workers and 118.515 microseconds from four to eight workers at p50; neither delta predicts a lazy-policy result.

## Delayed scheduler demand

The timing schema records scheduler creation and readiness, not delayed-task posting. It cannot date or identify a first delayed post. The native startup trace for this scope identifies a MemoryPool release task, so the scheduler is used by the normal empty launch rather than being an unused pool.

The source path is concrete. Memory allocation returns pages to `MemoryPool`, which checks whether to post a release task in [`memory-pool.cc`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/deps/v8/src/heap/memory-pool.cc#L406-L439). A stale deadline posts the first release with zero delay in [`memory-pool.cc`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/deps/v8/src/heap/memory-pool.cc#L520-L535). The release task posts through `PostDelayedTaskOnWorkerThread()` in [`memory-pool.cc`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/deps/v8/src/heap/memory-pool.cc#L497-L518). The default memory-pool timeout is eight seconds in [`memory-pool.h`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/deps/v8/src/heap/memory-pool.h#L82-L87), and a nonempty pool re-posts after each release in [`memory-pool.cc`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/deps/v8/src/heap/memory-pool.cc#L469-L489).

The scheduler's `PostDelayedTask()` queues local work and immediately calls `uv_async_send()` in [`src/node_platform.cc`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/src/node_platform.cc#L115-L140). Its worker initializes the loop and async handle before exposing readiness in [`src/node_platform.cc`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/src/node_platform.cc#L143-L153). Lazy initialization would therefore need a first-poster synchronization protocol that also races safely with `Shutdown()`.

The measured 174.236-microsecond default-ready duration is a separate relocation candidate, not a verified benefit. The current normal launch already posts delayed MemoryPool work, so a lazy scheduler moves initialization to that post path. The capture does not establish the post's deadline or whether a time-to-JavaScript metric can avoid its cost. That excludes a delayed-scheduler prototype on this evidence.

## Worker demand

Each empty and hello run posts exactly three worker tasks. The worker script posts 10 or 11. All 250 runs have maximum observed concurrent worker-task execution of one.

| Case | Task count | Task work p50 / p95 | Task makespan p50 / p95 | First post to first task p50 / p95 |
| --- | ---: | ---: | ---: | ---: |
| Default empty | 3 | 613.032 / 690.775 | 1,677.579 / 1,801.282 | 35.397 / 52.172 |
| One-worker empty | 3 | 461.973 / 532.804 | 1,540.377 / 1,679.048 | 39.992 / 62.434 |
| Eight-worker empty | 3 | 602.114 / 698.498 | 1,635.302 / 1,895.107 | 31.329 / 51.515 |
| Default hello | 3 | 626.777 / 694.989 | 5,662.123 / 5,935.180 | 31.002 / 50.608 |
| Default worker | 10–11 | 1,535.689 / 1,749.312 | 22,785.183 / 24,133.294 | 32.490 / 53.753 |

The empty launch is not a no-demand negative control. Its three tasks begin 35.397 microseconds after the first post at p50. Delaying creation until that post would move the construction cost onto a path that is currently ready.

Serial execution in these five workloads does not establish that four workers are unnecessary. It establishes only that this evidence does not observe a workload needing concurrent platform tasks during the capture window.

## Runtime constraints

The current worker thread enters the task queue after setting its name and emitting trace metadata in [`src/node_platform.cc`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/src/node_platform.cc#L51-L85). The delayed scheduler initializes its loop and `uv_async_t` before its readiness semaphore releases in [`src/node_platform.cc`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/src/node_platform.cc#L102-L112) and [`src/node_platform.cc`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/src/node_platform.cc#L143-L153).

The runner creates the scheduler, allocates every worker, and waits for all readiness signals before bootstrap continues in [`src/node_platform.cc`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/src/node_platform.cc#L243-L278). Task posting assumes the shared queue already exists in [`src/node_platform.cc`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/src/node_platform.cc#L280-L286). Shutdown stops that queue and joins every stored thread in [`src/node_platform.cc`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/src/node_platform.cc#L301-L307).

The existing `NumberOfWorkerThreads()` returns `threads_.size()`, which includes the delayed scheduler, in [`src/node_platform.cc`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/src/node_platform.cc#L309-L310). Job creation passes that count to V8 in [`src/node_platform.cc`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/src/node_platform.cc#L701-L718). A demand-driven implementation must preserve this observable capacity or change it deliberately; a simple lazy vector changes both the count and V8 job-handle limit.

## Recommendation

Do not prototype an adaptive pool from this evidence. The existing barrier-removal screen being neutral or slower rules out a synchronization-only claim. It does not test adaptive creation. The ordinary-pool construction span is 0.138 milliseconds at the default median and appears before worker work that every case needs. The separate delayed scheduler is used by the normal empty launch and measures 0.174 milliseconds to ready; it has no established end-to-end saving either.

Reopen only with a defined runtime policy and a matched uninstrumented end-to-end experiment. That policy must state how configured capacity, `NumberOfWorkerThreads()`, job-handle limits, first-post latency, delayed scheduling, shutdown, and embedding remain correct. Without that evidence, a prototype would trade a measured small construction segment for unmeasured latency and concurrency changes.
