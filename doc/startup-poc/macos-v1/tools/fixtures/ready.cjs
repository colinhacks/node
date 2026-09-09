const fs = require('node:fs');

function ready() {
  const fd = Number(process.env.STARTUP_LAB_READY_FD);
  if (Number.isInteger(fd) && fd >= 0) fs.writeSync(fd, '1');
}

module.exports = { ready };
