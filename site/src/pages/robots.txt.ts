// robots.txt: who may crawl the site, by purpose.
//
// ESSENCE_AI_TRAINING is "disallow" by default: search crawlers and fetchers that act for a person
// stay under "*", and crawlers that collect pages to train AI models get their own groups with
// "Disallow: /". The tokens were checked against each operator's own page on 2026-11-26 (the
// README's "The website" section lists the operators).
//
// Search crawlers and fetchers get no named group on purpose. Under RFC 9309 a crawler obeys only
// the most specific group that names it, so a named group would skip whatever "*" says.
// "allow" writes the "*" group alone.
import type { APIRoute } from "astro";
import { abs, aiTraining } from "../lib/project";

const policy = `# AI policy:
#   Search crawlers: allowed under "*" (Googlebot, bingbot, OAI-SearchBot, Claude-SearchBot,
#     PerplexityBot, Applebot, Amzn-SearchBot, meta-webindexer, MistralAI-Index, DuckAssistBot).
#   Fetchers acting for a person who asked a question just now: allowed under "*"
#     (ChatGPT-User, Claude-User, Perplexity-User, Google-Agent, MistralAI-User, Amzn-User,
#     meta-externalfetcher).
#   AI model training: not allowed. Groups below.

`;

const training = `
# Shared training-preference token (IETF draft-kelley-00). A "*" group never counts for it.
# Read by Anthropic since 2026-10-30, Microsoft from 2027-02-01, Google planned for early 2027.
User-agent: __usage_ai-training
Disallow: /

# Training crawlers and training-control tokens, named by their operators:
# OpenAI training (GPTBot); Anthropic training (ClaudeBot); Google Gemini training and
# non-Search grounding, no effect on Google Search (Google-Extended); Apple training, no effect
# on Apple search (Applebot-Extended); Common Crawl archive (CCBot); Meta training
# (meta-externalagent); Amazon training (Amazonbot); Mistral training (MistralAI-Training);
# Ai2 training (AI2Bot); ByteDance, undocumented by its operator (Bytespider).
User-agent: GPTBot
User-agent: ClaudeBot
User-agent: Google-Extended
User-agent: Applebot-Extended
User-agent: CCBot
User-agent: meta-externalagent
User-agent: Amazonbot
User-agent: MistralAI-Training
User-agent: AI2Bot
User-agent: Bytespider
Disallow: /
`;

export const GET: APIRoute = () => {
  const noTraining = aiTraining === "disallow";
  const body = `# robots.txt for ${abs("/")}

${noTraining ? policy : ""}User-agent: *
Allow: /
${
  noTraining
    ? `# IETF AIPREF draft vocabulary: no AI training (draft-ietf-aipref-attach-05; no confirmed reader yet)
Content-Usage: train-ai=n
${training}`
    : ""
}
Sitemap: ${abs("/sitemap.xml")}
`;
  return new Response(body, {
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });
};
