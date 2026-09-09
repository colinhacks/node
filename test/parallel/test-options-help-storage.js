// Flags: --expose-internals --expose-gc --no-warnings

'use strict';
require('../common');
const assert = require('assert');
const { internalBinding } = require('internal/test/binding');
const {
  getCLIOptionsInfo,
  getEnvOptionsInputType,
  getNamespaceOptionsInputType,
} = internalBinding('options');

const first = getCLIOptionsInfo();
const descriptions = new Map();
for (const [name, info] of first.options) {
  assert.strictEqual(typeof info.helpText, 'string');
  descriptions.set(name, info.helpText);
  info.helpText = 'changed in JavaScript';
}
assert(descriptions.size > 0);
global.gc();

const second = getCLIOptionsInfo();
for (const [name, info] of second.options) {
  assert.strictEqual(info.helpText, descriptions.get(name));
}

function checkDescriptions(options) {
  for (const [name, info] of Object.entries(options)) {
    assert.strictEqual(info.description, descriptions.get(name));
  }
}

checkDescriptions(getEnvOptionsInputType());
for (const options of getNamespaceOptionsInputType().values()) {
  checkDescriptions(options);
}
