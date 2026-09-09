'use strict';

const { performance } = require('node:perf_hooks');
const { Worker, isMainThread, parentPort } = require('node:worker_threads');

function timing() {
  const node = performance.nodeTiming;
  return {
    nodeStart: node.nodeStart,
    v8Start: node.v8Start,
    bootstrapComplete: node.bootstrapComplete,
    environment: node.environment,
  };
}

function emit(payload) {
  process.stdout.write(`${JSON.stringify(payload)}\n`);
}

function errorPayload(err) {
  return {
    code: err?.code ?? null,
    message: err?.message ?? String(err),
    opensslErrorStack: err?.opensslErrorStack ?? [],
  };
}

if (!isMainThread) {
  try {
    require('node:crypto').randomBytes(4);
    parentPort.postMessage({ ok: true });
  } catch (err) {
    parentPort.postMessage({ ok: false, error: errorPayload(err) });
  }
  return;
}

const mode = process.env.ENTROPY_MODE ?? 'default';
const iterations = Number.parseInt(process.env.ENTROPY_ITERATIONS ?? '5000', 10);

async function main() {
  const payload = {
    mode,
    openssl: process.versions.openssl,
    timing: timing(),
  };

  if (mode === 'startup') {
    emit({ ok: true, ...payload });
    return;
  }

  if (mode === 'workers') {
    const workers = Array.from({ length: 8 }, () => new Worker(__filename));
    const results = await Promise.all(workers.map((worker) => new Promise((resolve) => {
      let message = null;
      worker.once('message', (value) => { message = value; });
      worker.once('error', (err) => { message = { ok: false, error: errorPayload(err) }; });
      worker.once('exit', (code) => resolve({ code, message }));
    })));
    emit({ ok: true, ...payload, workers: results });
    return;
  }

  const beforeRequire = performance.now();
  const crypto = require('node:crypto');
  const afterRequire = performance.now();

  if (mode === 'fips') {
    emit({ ok: true, ...payload, fips: crypto.getFips() });
    return;
  }

  if (mode === 'throughput') {
    const started = performance.now();
    for (let index = 0; index < iterations; index += 1) crypto.randomBytes(64);
    const elapsedMs = performance.now() - started;
    emit({
      ok: true,
      ...payload,
      requireMs: afterRequire - beforeRequire,
      elapsedMs,
      iterations,
      opsPerSecond: iterations / (elapsedMs / 1000),
    });
    return;
  }

  const beforeRandom = performance.now();
  const bytes = crypto.randomBytes(32);
  const afterRandom = performance.now();
  const sha256 = crypto.createHash('sha256').update(bytes).digest('hex');
  const hashes = crypto.getHashes();
  emit({
    ok: true,
    ...payload,
    requireMs: afterRequire - beforeRequire,
    firstRandomMs: afterRandom - beforeRandom,
    sha256,
    sha256Available: hashes.includes('sha256'),
    md4Available: hashes.includes('md4'),
    fips: crypto.getFips(),
  });
}

main().catch((err) => {
  emit({ ok: false, mode, error: errorPayload(err), timing: timing() });
  process.exitCode = 1;
});
