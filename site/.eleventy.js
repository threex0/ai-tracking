const path = require('path');

const ROOT = path.resolve(__dirname, '..');

module.exports = function (eleventyConfig) {
  eleventyConfig.addPassthroughCopy('src/assets');

  eleventyConfig.addCollection('digests', (c) =>
    c.getFilteredByGlob('src/content/digests/*.md').sort((a, b) => (b.date || 0) - (a.date || 0)));
  eleventyConfig.addCollection('stories', (c) =>
    c.getFilteredByGlob('src/content/stories/*.md').sort((a, b) => (b.date || 0) - (a.date || 0)));
  eleventyConfig.addCollection('ideas', (c) =>
    c.getFilteredByGlob('src/content/ideas/*.md').sort((a, b) => (b.date || 0) - (a.date || 0)));

  eleventyConfig.addFilter('fmtDate', (v) => {
    if (!v) return '';
    const d = new Date(v);
    return Number.isNaN(d.getTime()) ? '' : d.toISOString().slice(0, 10);
  });

  return {
    dir: {
      input: 'src',
      output: path.join(ROOT, 'output', 'site'),
      includes: '_includes',
      layouts: '_includes/layouts',
      data: '_data',
    },
  };
};
