const { Worker } = require('node:worker_threads');
const { ready } = require('./ready.cjs');

const worker = new Worker('require("node:worker_threads").parentPort.postMessage("ready")', { eval: true });
worker.once('message', () => {
  ready();
  worker.terminate();
});
