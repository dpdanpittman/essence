// robots.txt: who may crawl the site, by purpose. Tokens checked against each vendor's own
// documentation on 2026-11-26 (the README's "The website" section lists the pages).
// The training group follows ESSENCE_AI_TRAINING ("allow" by default, or "disallow").
// PENDING-DECISION(5): the live site's answer for training crawlers. The recommendation is allow.
import type { APIRoute } from 'astro';
import { abs, aiTraining } from '../lib/project';

export const GET: APIRoute = () => {
  const training = aiTraining === 'disallow' ? 'Disallow: /' : 'Allow: /';
  const body = `# robots.txt for ${abs('/')}

# Search and answer engines that index the site: allowed.
User-agent: Googlebot
User-agent: bingbot
User-agent: Applebot
User-agent: OAI-SearchBot
User-agent: Claude-SearchBot
User-agent: PerplexityBot
Allow: /

# Fetchers that act for a person who asked about a page: allowed.
User-agent: ChatGPT-User
User-agent: Claude-User
User-agent: Perplexity-User
Allow: /

# Collection for training AI models: ${aiTraining === 'disallow' ? 'not allowed' : 'allowed'}.
# __usage_ai-training is the training preference token of an IETF draft. The "*" group does not cover it.
# Google-Extended also covers grounding in Gemini apps. It does not change Google Search.
User-agent: GPTBot
User-agent: ClaudeBot
User-agent: Google-Extended
User-agent: Applebot-Extended
User-agent: CCBot
User-agent: __usage_ai-training
${training}

# Everyone else.
User-agent: *
Allow: /

Sitemap: ${abs('/sitemap.xml')}
`;
  return new Response(body, { headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
};
