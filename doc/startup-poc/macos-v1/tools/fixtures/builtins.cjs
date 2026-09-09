const assert = require('node:assert');
const path = require('node:path');
const url = require('node:url');
const { ready } = require('./ready.cjs');

assert.strictEqual(path.basename(url.fileURLToPath(new URL(`file://${__filename}`))), path.basename(__filename));
ready();
