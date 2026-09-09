const http = require('node:http');
const { ready } = require('./ready.cjs');

const server = http.createServer((_, response) => response.end());
server.listen(0, '127.0.0.1', () => {
  ready();
  server.close();
});
