const fs = require('fs');
const path = require('path');

module.exports = function () {
  const p = path.join(__dirname, '..', '..', '..', 'sources.json');
  if (!fs.existsSync(p)) return [];
  try {
    return JSON.parse(fs.readFileSync(p, 'utf8')).sources || [];
  } catch {
    return [];
  }
};
