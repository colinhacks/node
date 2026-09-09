'use strict';

const common = require('../common');
if (!common.hasCrypto)
  common.skip('missing crypto');

const {
  hasOpenSSL,
  isBoringSSL,
} = require('../common/crypto');

if (common.isAIX)
  common.skip('AIX retains OpenSSL for V8 entropy');

if (isBoringSSL)
  common.skip('BoringSSL does not have OpenSSL providers');

if (!hasOpenSSL(3))
  common.skip('this test requires OpenSSL 3.x');

const crypto = require('node:crypto');
if (crypto.getFips())
  common.skip('this test cannot be run in FIPS mode');

const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fixtures = require('../common/fixtures');

const timeout = common.platformTimeout(10_000);

function runSecureHeapWorkers() {
  const { Worker } = require('node:worker_threads');
  const workers = 8;

  for (let i = 0; i < workers; i++) {
    const worker = new Worker(`
      const { parentPort } = require('node:worker_threads');
      try {
        require('node:crypto').randomBytes(4);
        parentPort.postMessage({ ok: true });
      } catch (err) {
        if (err.code !== 'ERR_OSSL_CRYPTO_SECURE_MALLOC_FAILURE') throw err;
        parentPort.postMessage({ error: err.code });
      }
    `, { eval: true });

    worker.on('error', common.mustNotCall());
    worker.on('message', common.mustCall((message) => {
      assert(message.ok === true ||
             message.error === 'ERR_OSSL_CRYPTO_SECURE_MALLOC_FAILURE');
    }));
    worker.on('exit', common.mustCall((code) => {
      assert.strictEqual(code, 0);
    }));
  }
}

if (process.argv[2] === 'secure-heap-workers') {
  runSecureHeapWorkers();
  return;
}

function run(args) {
  const child = spawnSync(process.execPath, args, {
    encoding: 'utf8',
    timeout,
  });
  assert.ifError(child.error);
  assert.strictEqual(child.signal, null,
                     `child timed out or crashed: ${child.stderr}`);
  return child;
}

function assertHash(args, expected) {
  const includeMd4 = Object.hasOwn(expected, 'md4');
  const child = run([...args, '-e', `
    const crypto = require('node:crypto');
    const result = {
      sha256: crypto.createHash('sha256').update('abc').digest('hex'),
    };
    if (${includeMd4})
      result.md4 = crypto.createHash('md4').update('abc').digest('hex');
    process.stdout.write(JSON.stringify(result));
  `]);
  assert.strictEqual(child.status, 0, child.stderr);
  assert.deepStrictEqual(JSON.parse(child.stdout), expected);
}

// Crypto remains available after entropy is supplied to V8 from the OS.
assertHash([], {
  sha256: 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad',
});

// Explicitly loading the legacy provider must not hide the default provider.
assertHash(['--openssl-legacy-provider'], {
  sha256: 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad',
  md4: 'a448017aaf21d8525fc10ae87aa6729d',
});

{
  // An unfetchable DRBG must not abort before JavaScript or hang. The deferred
  // OpenSSL crypto call reports the provider error instead.
  const randomConf = fixtures.path('openssl3-conf', 'random_unavailable.cnf');
  const child = run([`--openssl-config=${randomConf}`, '-e', `
    process.stdout.write('started\\n');
    require('node:crypto').randomBytes(8);
  `]);
  assert.strictEqual(child.status, 1, child.stderr);
  assert.match(child.stdout, /^started$/m);
  assert.match(child.stderr, /unable to fetch drbg/i);
}

if (!common.isWindows && !common.isASan) {
  const child = run([
    '--secure-heap=1024',
    '--secure-heap-min=4',
    __filename,
    'secure-heap-workers',
  ]);
  assert.strictEqual(child.status, 0, child.stderr);
}
