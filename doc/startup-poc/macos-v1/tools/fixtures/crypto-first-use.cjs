const { createHash } = require('node:crypto');
const { ready } = require('./ready.cjs');

createHash('sha256').update('startup-lab').digest();
ready();
