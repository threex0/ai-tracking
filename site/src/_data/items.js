const fs = require('fs');
const path = require('path');

module.exports = function () {
  const p = path.join(__dirname, '..', '..', '..', 'data', 'items.json');
  if (!fs.existsSync(p)) return [];
  try {
    return JSON.parse(fs.readFileSync(p, 'utf8'));
  } catch {
    return [];
  }
};
