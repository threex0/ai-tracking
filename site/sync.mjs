// Copies the generated markdown reports from output/{digests,stories,ideas}
// into src/content with frontmatter (title/slug/date/permalink) so Eleventy
// can build one page per report. Run before `eleventy`.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const CONTENT_ROOT = path.join(__dirname, 'src', 'content');

function syncMarkdown(srcDir, destDir, permalinkBase) {
  if (!fs.existsSync(srcDir)) return;
  fs.mkdirSync(destDir, { recursive: true });
  for (const f of fs.readdirSync(srcDir)) {
    if (!f.endsWith('.md')) continue;
    const body = fs.readFileSync(path.join(srcDir, f), 'utf8');
    const date = f.replace(/\.md$/, '');
    const first = (body.split('\n').find((l) => l.startsWith('# ')) || `# ${date}`)
      .replace(/^#\s+/, '')
      .trim();
    const fm = [
      '---',
      `title: ${JSON.stringify(first)}`,
      `slug: "${date}"`,
      `date: "${date}"`,
      'layout: base',
      `permalink: /${permalinkBase}/{{ slug }}/`,
      '---',
      '',
      '',
    ].join('\n');
    fs.writeFileSync(path.join(destDir, f), fm + body);
  }
}

syncMarkdown(path.join(ROOT, 'output', 'digests'), path.join(CONTENT_ROOT, 'digests'), 'digests');
syncMarkdown(path.join(ROOT, 'output', 'stories'), path.join(CONTENT_ROOT, 'stories'), 'stories');
syncMarkdown(path.join(ROOT, 'output', 'ideas'), path.join(CONTENT_ROOT, 'ideas'), 'ideas');

console.log('site: synced markdown reports into src/content');
