// Facts about the project and about this copy of the site, read once at build time.
//
// The project facts come from the repository itself, so the page cannot drift from them:
//   - the website, repository and author lines at the top of README.md;
//   - the version and its date from the newest release heading in CHANGELOG.md;
//   - the last update date from the newest git commit (or ESSENCE_UPDATED, or the release date).
//
// Everything that belongs to one deployment and not to the project (analytics, the shared
// footer, the privacy page's operator and contact) is an ESSENCE_* environment variable with a
// safe default, so a copy of this site carries none of it. The README's "The website" section
// lists every variable.

import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

const env = (name: string) => (process.env[name] || "").trim();

// `npm run build` runs in site/, so the repository root is one level up.
const ROOT = env("ESSENCE_REPO_ROOT") || path.resolve(process.cwd(), "..");

function readRepoFile(name: string): string {
  const file = path.join(ROOT, name);
  if (!existsSync(file)) {
    throw new Error(
      `site build: ${name} not found in ${ROOT}. Run the build from site/ or set ESSENCE_REPO_ROOT.`,
    );
  }
  return readFileSync(file, "utf8");
}

const readme = readRepoFile("README.md");
const changelog = readRepoFile("CHANGELOG.md");

function readmeLine(label: string): string {
  const m = readme.match(new RegExp(`^- ${label}: (.+)$`, "m"));
  return m ? m[1].trim() : "";
}

function stripSlash(url: string) {
  return url.replace(/\/+$/, "");
}

// ---------- the project ----------

/** The live address of the site, without a trailing slash. ESSENCE_SITE_URL wins over the README. */
export const siteUrl = stripSlash(
  env("ESSENCE_SITE_URL") || readmeLine("Website"),
);
if (!/^https?:\/\/[^/]+$/.test(siteUrl)) {
  throw new Error(
    `site build: the site URL "${siteUrl}" is not an origin such as https://example.org`,
  );
}
export const siteHost = new URL(siteUrl).host;

/** The source repository. */
export const repoUrl = stripSlash(readmeLine("Repository"));

// "- Author: Essence is built by NAME (URL)"
const author = readmeLine("Author").match(
  /built by (.+?) \((https?:\/\/[^)]+)\)/,
);
export const authorName = author ? author[1] : "";
export const authorUrl = author ? author[2] : "";

// The newest released version: the first "## [X.Y.Z] - YYYY-MM-DD" heading.
const release = changelog.match(
  /^## \[(\d+\.\d+\.\d+)\]\s*[-–—]\s*(\d{4}-\d{2}-\d{2})/m,
);
export const version = release ? release[1] : "";
export const releaseDate = release ? release[2] : "";

function gitDate(): string {
  try {
    const out = execFileSync("git", ["-C", ROOT, "log", "-1", "--format=%cs"], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
      timeout: 5000,
    }).trim();
    return /^\d{4}-\d{2}-\d{2}$/.test(out) ? out : "";
  } catch {
    return "";
  }
}

/** The date of the last change to the project, YYYY-MM-DD. */
export const updated = env("ESSENCE_UPDATED") || gitDate() || releaseDate;

export const license = {
  spdx: "AGPL-3.0-or-later",
  name: "GNU AGPL 3.0 or later",
  url: repoUrl
    ? `${repoUrl}/blob/main/LICENSE`
    : "https://www.gnu.org/licenses/agpl-3.0.html",
};

/** The one line that installs it. */
export const installLine = repoUrl
  ? `git clone ${repoUrl}.git && cd ${repoUrl.split("/").pop()} && ./install.sh`
  : "./install.sh";

export const title = "Essence · an AI that remembers who it is";
export const description =
  "Essence is a small set of files and hooks that carries a Claude Code agent across the gap between sessions: who it is with its person, and the picture of each area of work.";

/** An absolute URL on this site. */
export const abs = (p: string) => siteUrl + (p.startsWith("/") ? p : `/${p}`);

// ---------- this deployment ----------

/** Analytics. Off unless ESSENCE_UMAMI_ID is set: a self-hosted Umami tracker at /u/m.js, no cookies. */
export const umamiId = env("ESSENCE_UMAMI_ID");
export const umamiDomains = env("ESSENCE_UMAMI_DOMAINS");

/** How often the Umami server changes the salt of its visitor code: "month" (Umami's default) or "day". */
export const umamiSalt: "month" | "day" =
  env("ESSENCE_UMAMI_SALT") === "day" ? "day" : "month";

/** How long the Umami server keeps its data, in words ("25 months"). Unset: until the operator deletes it. */
export const umamiRetention = env("ESSENCE_UMAMI_RETENTION");

/** Umami click events, only when analytics is on. Spread onto an element: {...track('github')}. */
export function track(
  event: string,
  data: Record<string, string> = {},
): Record<string, string> {
  if (!umamiId) return {};
  const attrs: Record<string, string> = { "data-umami-event": event };
  for (const [k, v] of Object.entries(data)) attrs[`data-umami-event-${k}`] = v;
  return attrs;
}

// ESSENCE_FOOTER_LINKS: a row of related sites in the footer. "Label=https://url;Label=https://url".
// Unset: no row.
export const footerLinks = env("ESSENCE_FOOTER_LINKS")
  .split(";")
  .map((pair) => pair.trim())
  .filter(Boolean)
  .map((pair) => {
    const i = pair.indexOf("=");
    const label = pair.slice(0, i).trim();
    const href = pair.slice(i + 1).trim();
    if (i < 1 || !/^https:\/\//.test(href))
      throw new Error(`ESSENCE_FOOTER_LINKS: bad entry "${pair}"`);
    const host = new URL(href).host;
    const parts = host.split(".");
    return {
      label,
      href,
      target: parts.length > 2 ? parts[0] : host,
      current: host === siteHost,
    };
  });

// ESSENCE_REL_ME: profile URLs that belong to the same person, as <link rel="me">. Space or comma separated.
export const relMe = env("ESSENCE_REL_ME")
  .split(/[\s,]+/)
  .filter(Boolean)
  .map((url) => {
    if (!/^https:\/\//.test(url))
      throw new Error(`ESSENCE_REL_ME: not an https URL: "${url}"`);
    return url;
  });

// ESSENCE_PRIVACY: "off" (the default: no privacy page), "draft" (built, noindex, marked Draft, not
// linked, not in the sitemap) or "live" (linked from the footer and in the sitemap).
const privacyMode = env("ESSENCE_PRIVACY");
export const privacy = {
  mode: (privacyMode === "live" || privacyMode === "draft"
    ? privacyMode
    : "off") as "off" | "draft" | "live",
  operator: env("ESSENCE_PRIVACY_OPERATOR"),
  contact: env("ESSENCE_PRIVACY_CONTACT"),
  date: env("ESSENCE_PRIVACY_DATE"),
  logs: env("ESSENCE_PRIVACY_LOGS"),
};
if (privacy.mode === "live") {
  const missing = (["operator", "contact", "date", "logs"] as const).filter(
    (k) => !privacy[k],
  );
  if (missing.length) {
    throw new Error(
      `ESSENCE_PRIVACY=live needs ${missing.map((k) => `ESSENCE_PRIVACY_${k.toUpperCase()}`).join(", ")}`,
    );
  }
  if (!/^\d{4}-\d{2}-\d{2}$/.test(privacy.date))
    throw new Error("ESSENCE_PRIVACY_DATE must be YYYY-MM-DD");
}
export const privacyLinked = privacy.mode === "live";

/** AI training crawlers in robots.txt: "allow" (default) or "disallow". */
export const aiTraining: "allow" | "disallow" =
  env("ESSENCE_AI_TRAINING") === "disallow" ? "disallow" : "allow";
