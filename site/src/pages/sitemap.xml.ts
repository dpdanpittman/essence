// sitemap.xml: every indexable page with a true last-modified date. No priority or change frequency.
// The home page changes with the project, so its date is the last update (src/lib/project.ts).
// The privacy page enters only when it is live, with the date it took effect.
import type { APIRoute } from 'astro';
import { abs, updated, privacy } from '../lib/project';

export const GET: APIRoute = () => {
  const pages: { loc: string; lastmod: string }[] = [{ loc: abs('/'), lastmod: updated }];
  if (privacy.mode === 'live') pages.push({ loc: abs('/privacy/'), lastmod: privacy.date });
  const urls = pages
    .map((p) => `  <url>\n    <loc>${p.loc}</loc>${p.lastmod ? `\n    <lastmod>${p.lastmod}</lastmod>` : ''}\n  </url>`)
    .join('\n');
  const body = `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls}\n</urlset>\n`;
  return new Response(body, { headers: { 'Content-Type': 'application/xml; charset=utf-8' } });
};
