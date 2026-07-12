/**
 * Facebook Playwright scraper - Vercel Node.js serverless function.
 *
 * WHY THIS EXISTS:
 * The Python side used to rely on the `facebook-scraper` pip library, which
 * does plain HTTP requests + HTML parsing. That approach kept breaking on
 * share-link redirects, tracking query params, and page-variant differences
 * that a real browser handles transparently (it just renders the page like
 * a human would, following any JS/meta redirects on its own).
 *
 * This function uses a real headless Chromium (via @sparticuz/chromium, a
 * build slimmed down to fit Vercel's serverless size limit) driven by
 * playwright-core, so we get the same rendering a real visitor gets -
 * including any client-side bounce/redirect logic - instead of guessing at
 * Facebook's HTTP response shape ourselves.
 *
 * STABILITY MEASURES:
 *  - Browser instance is cached at module scope and reused across warm
 *    invocations (cold start is the expensive part - avoid repeating it).
 *  - Non-essential resources (images/fonts/media/stylesheets) are blocked
 *    so pages load faster and use less memory.
 *  - Multiple independent extraction strategies (aria-label parsing,
 *    visible text patterns, meta tags) so a single DOM change doesn't take
 *    everything down at once.
 *  - Explicit, structured error responses instead of ever returning fake
 *    zeroed stats - the Python caller decides how to surface failures.
 *  - A shared-secret header requirement, since this endpoint is expensive
 *    to call (spins up a real browser) and shouldn't be left open.
 *
 * ENV VARS:
 *  FACEBOOK_C_USER, FACEBOOK_XS   - same cookies already used elsewhere
 *  INTERNAL_SCRAPE_SECRET         - shared secret checked against the
 *                                   x-internal-secret request header
 */

const chromium = require('@sparticuz/chromium-min');

// Some errors from the Chromium download/extraction pipeline (e.g. a
// corrupted/partial tar from a previous invocation that got killed mid-
// download by the function timeout) surface as raw stream 'error' events
// rather than a rejected Promise - these bypass any try/catch around
// `await chromium.executablePath()` entirely and crash the process. We
// can't catch and recover the CURRENT request in that case, but we can at
// least wipe the corrupted cache here so the next invocation gets a clean
// download instead of hitting the exact same crash forever.
process.on('uncaughtException', (err) => {
  console.error('[facebook-scrape] uncaughtException:', err && err.message);
  try {
    cleanCachedChromium();
  } catch (e) {
    /* best effort */
  }
});
process.on('unhandledRejection', (reason) => {
  console.error('[facebook-scrape] unhandledRejection:', reason);
});
const { chromium: playwright } = require('playwright-core');

// Pinned to a version confirmed to still support CommonJS (v149+ dropped it).
// The pack tar is fetched from Sparticuz's own GitHub release on cold start
// and cached in /tmp for warm reuse - see their docs for how this works.
const CHROMIUM_PACK_URL =
  'https://github.com/Sparticuz/chromium/releases/download/v131.0.1/chromium-v131.0.1-pack.x64.tar';

const NAV_TIMEOUT_MS = 45000;
const BLOCKED_RESOURCE_TYPES = new Set(['image', 'font', 'media', 'stylesheet']);

// Reused across warm invocations of the same serverless instance.
let browserPromise = null;

const fs = require('fs');

function cleanCachedChromium() {
  const paths = [
    '/tmp/chromium',
    '/tmp/chromium-pack',
    '/tmp/swiftshader',
    '/tmp/al2023.tar.br',
    '/tmp/al2023',
    '/tmp/fonts.tar.br',
    '/tmp/fonts',
  ];
  for (const p of paths) {
    try {
      fs.rmSync(p, { recursive: true, force: true });
    } catch (e) {
      /* ignore - best effort cleanup */
    }
  }
}

// ════════════════════════════════════════════════════════════════
// FORCE CLEANUP ON EVERY COLD START - prevent corrupted tar cache
// ════════════════════════════════════════════════════════════════

function forceCleanTmp() {
  const paths = [
    '/tmp/chromium',
    '/tmp/chromium-pack',
    '/tmp/swiftshader',
    '/tmp/al2023.tar.br',
    '/tmp/al2023',
    '/tmp/fonts.tar.br',
    '/tmp/fonts',
  ];
  let cleanedCount = 0;
  for (const p of paths) {
    try {
      if (fs.existsSync(p)) {
        fs.rmSync(p, { recursive: true, force: true });
        console.log('[facebook-scrape] Cleaned up:', p);
        cleanedCount++;
      }
    } catch (e) {
      console.warn('[facebook-scrape] Cleanup failed for', p, e.message);
    }
  }
  if (cleanedCount > 0) {
    console.log('[facebook-scrape] Cleaned', cleanedCount, 'paths from /tmp');
  }
}

// Call ini SEKARANG, sebelum chromium.executablePath() dipanggil
console.log('[facebook-scrape] Module initialized, cleaning /tmp...');
forceCleanTmp();

async function launchBrowser() {
  const executablePath = await chromium.executablePath(CHROMIUM_PACK_URL);
  return playwright.launch({
    args: chromium.args,
    executablePath,
    headless: true,
  });
}

async function getBrowser() {
  if (browserPromise) {
    try {
      const existing = await browserPromise;
      if (existing.isConnected()) return existing;
    } catch (e) {
      // fall through and relaunch
    }
    browserPromise = null;
  }

  try {
    browserPromise = launchBrowser();
    return await browserPromise;
  } catch (firstError) {
    // Most likely cause: a previous cold start got killed mid-download by
    // the function timeout, leaving a corrupted/partial chromium pack
    // cached in /tmp - every invocation after that keeps failing the same
    // way until that stale cache is cleared. Wipe it and retry once with
    // a fresh download before giving up.
    browserPromise = null;
    cleanCachedChromium();
    try {
      browserPromise = launchBrowser();
      return await browserPromise;
    } catch (secondError) {
      browserPromise = null;
      throw new Error(
        `Browser launch failed even after clearing cached Chromium files. ` +
        `First error: ${firstError.message}. Retry error: ${secondError.message}`
      );
    }
  }
}

function parseCount(str) {
  if (!str) return 0;
  const cleaned = str.trim().toUpperCase().replace(/,/g, '');
  const match = cleaned.match(/^([\d.]+)\s*([KM]?)$/);
  if (!match) {
    const digitsOnly = cleaned.replace(/[^\d]/g, '');
    return digitsOnly ? parseInt(digitsOnly, 10) : 0;
  }
  let n = parseFloat(match[1]);
  if (match[2] === 'K') n *= 1000;
  if (match[2] === 'M') n *= 1000000;
  return Math.round(n);
}

/**
 * Extraction runs inside the browser page context (page.evaluate), so this
 * whole function is serialized and executed client-side - it can only use
 * plain DOM APIs, no closures over outer Node variables/requires.
 */
function extractPostDataInPage() {
  function textOf(el) {
    return (el.getAttribute('aria-label') || el.innerText || '').trim();
  }

  function findFirstMatch(patterns) {
    const candidates = document.querySelectorAll('span, a, div[role="button"], div');
    for (const el of candidates) {
      const text = textOf(el);
      if (!text || text.length > 60) continue; // skip huge blocks, we want short labels
      for (const pattern of patterns) {
        const m = text.match(pattern);
        if (m) return m[1];
      }
    }
    return null;
  }

  const likeRaw = findFirstMatch([
    /^([\d.,]+[KM]?)\s*(?:people )?reacted/i,
    /^Like:\s*([\d.,]+[KM]?)/i,
    /^([\d.,]+[KM]?)\s*(?:Like|Likes|reactions?)\b/i,
  ]);
  const commentRaw = findFirstMatch([
    /^([\d.,]+[KM]?)\s*comments?\b/i,
  ]);
  const shareRaw = findFirstMatch([
    /^([\d.,]+[KM]?)\s*shares?\b/i,
  ]);
  const viewRaw = findFirstMatch([
    /^([\d.,]+[KM]?)\s*views?\b/i,
  ]);

  const metaContent = (prop) => document.querySelector(`meta[property="${prop}"]`)?.content || '';

  return {
    likes_raw: likeRaw,
    comments_raw: commentRaw,
    shares_raw: shareRaw,
    views_raw: viewRaw,
    title: metaContent('og:title'),
    description: metaContent('og:description'),
    has_video_meta: !!metaContent('og:video'),
    final_url: window.location.href,
    page_title: document.title,
    debug_snippet: document.body ? document.body.innerText.slice(0, 400) : '',
  };
}

async function scrapePost(page, targetUrl) {
  await page.goto(targetUrl, { waitUntil: 'networkidle', timeout: NAV_TIMEOUT_MS });
  // Give lazy-loaded reaction/comment counts a moment to render.
  await page.waitForTimeout(2500);

  const raw = await page.evaluate(extractPostDataInPage);

  return {
    likes: parseCount(raw.likes_raw),
    comments: parseCount(raw.comments_raw),
    shares: parseCount(raw.shares_raw),
    views: parseCount(raw.views_raw),
    title: raw.title,
    description: raw.description,
    is_video: raw.has_video_meta,
    final_url: raw.final_url,
    _debug: raw,
  };
}

module.exports = async (req, res) => {
  const expectedSecret = process.env.INTERNAL_SCRAPE_SECRET;
  if (expectedSecret && req.headers['x-internal-secret'] !== expectedSecret) {
    res.status(401).json({ error: 'unauthorized' });
    return;
  }

  const targetUrl = req.query.url;
  if (!targetUrl) {
    res.status(400).json({ error: 'missing_url_param' });
    return;
  }

  let context = null;
  try {
    const browser = await getBrowser();
    context = await browser.newContext({
      viewport: { width: 1280, height: 1024 },
      userAgent:
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ' +
        '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
      locale: 'en-US',
    });

    const cUser = (process.env.FACEBOOK_C_USER || '').trim();
    const xs = (process.env.FACEBOOK_XS || '').trim();
    if (cUser && xs) {
      await context.addCookies([
        { name: 'c_user', value: cUser, domain: '.facebook.com', path: '/' },
        { name: 'xs', value: xs, domain: '.facebook.com', path: '/' },
      ]);
    }

    const page = await context.newPage();
    await page.route('**/*', (route) => {
      const type = route.request().resourceType();
      if (BLOCKED_RESOURCE_TYPES.has(type)) {
        route.abort();
      } else {
        route.continue();
      }
    });

    const result = await scrapePost(page, targetUrl);
    await context.close();
    context = null;

    const gotAnything =
      result.likes || result.comments || result.shares || result.views || result.title;

    if (!gotAnything) {
      res.status(404).json({
        error: 'no_data_extracted',
        message:
          'The page loaded but none of the expected post elements were found - it may ' +
          'require login, be private/deleted, or Facebook changed its layout again.',
        debug: result._debug,
      });
      return;
    }

    res.status(200).json({ success: true, data: result });
  } catch (err) {
    if (context) {
      try {
        await context.close();
      } catch (e) {
        /* ignore cleanup error */
      }
    }
    res.status(500).json({ error: 'scrape_failed', message: String((err && err.message) || err) });
  }
};
