import { defineConfig } from 'astro/config';

export default defineConfig({
  base: '/',   // the site is served at the root of its domain (a sub-path base broke every asset link on 2026-11-15)
  output: 'static',
  // One address per page: pages are folders (/privacy/), and the web server redirects /privacy to /privacy/.
  trailingSlash: 'always',
  build: { format: 'directory' },
});
