import { defineConfig } from 'astro/config';

export default defineConfig({
  base: '/',   // the site is served at the root of essence.mabus.ai (a '/essence' base broke every asset link on 2026-11-15)
  output: 'static',
});
