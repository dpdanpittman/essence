// feed.xml: an RSS 2.0 feed of the released versions, one item per release heading in
// CHANGELOG.md ("## [X.Y.Z] - YYYY-MM-DD"). "Unreleased" is left out. The item text is the
// release's own changelog section, as plain text.
import type { APIRoute } from "astro";
import { abs, repoUrl, releases } from "../lib/project";

const esc = (s: string) =>
  s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");

const rfc822 = (date: string) => new Date(`${date}T00:00:00Z`).toUTCString();

export const GET: APIRoute = () => {
  const changelogUrl = repoUrl ? `${repoUrl}/blob/main/CHANGELOG.md` : abs("/");
  const items = releases
    .map(
      (r) => `    <item>
      <title>Essence ${esc(r.version)}</title>
      <link>${esc(changelogUrl)}</link>
      <guid isPermaLink="false">essence-${esc(r.version)}</guid>
      <pubDate>${rfc822(r.date)}</pubDate>
      <description>${esc(r.notes)}</description>
    </item>`,
    )
    .join("\n");
  const body = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>Essence releases</title>
    <link>${abs("/")}</link>
    <atom:link href="${abs("/feed.xml")}" rel="self" type="application/rss+xml" />
    <description>Each released version of Essence, with its changelog notes.</description>
    <language>en</language>${releases[0] ? `\n    <lastBuildDate>${rfc822(releases[0].date)}</lastBuildDate>` : ""}
${items}
  </channel>
</rss>
`;
  return new Response(body, {
    headers: { "Content-Type": "application/rss+xml; charset=utf-8" },
  });
};
