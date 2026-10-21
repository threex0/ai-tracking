const fs = require('fs');
const path = require('path');

function loadJson(p, fallback) {
  if (!fs.existsSync(p)) return fallback;
  try {
    return JSON.parse(fs.readFileSync(p, 'utf8'));
  } catch {
    return fallback;
  }
}

module.exports = function () {
  const items = loadJson(path.join(__dirname, '..', '..', '..', 'data', 'items.json'), []);
  const sources = loadJson(path.join(__dirname, '..', '..', '..', 'sources.json'), { sources: [] }).sources || [];
  const nameById = Object.fromEntries(sources.map((s) => [s.id, s.name]));

  const tagCounts = new Map();
  const sourceCounts = new Map();
  for (const it of items) {
    for (const t of it.tags || []) tagCounts.set(t, (tagCounts.get(t) || 0) + 1);
    sourceCounts.set(it.source_id, (sourceCounts.get(it.source_id) || 0) + 1);
  }

  const byTag = [...tagCounts.entries()]
    .map(([tag, count]) => ({ tag, count }))
    .sort((a, b) => b.count - a.count || a.tag.localeCompare(b.tag));

  const bySource = [...sourceCounts.entries()]
    .map(([id, count]) => ({ id, name: nameById[id] || id, count }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));

  const recent = [...items]
    .sort((a, b) => new Date(b.fetched_at || 0) - new Date(a.fetched_at || 0))
    .slice(0, 30);

  return { total: items.length, byTag, bySource, recent };
};
