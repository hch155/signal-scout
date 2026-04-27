/**
 * Cloudflare Worker — proxy signal-scout.com → Cloud Run service
 *
 * Why this exists
 * ---------------
 * `signal-scout.com` historically pointed to Squarespace, which 302s
 * to the Cloud Run URL but strips the path. That breaks any URL with
 * a path component — most importantly OAuth callbacks
 * (`/auth/{provider}/callback`), `/account`, deep-linked `/data`,
 * etc. Cloud Run gen2 in europe-central2 doesn't currently expose
 * native custom-domain mapping for the apex, and Cloudflare Origin
 * Rules' Host-header rewrite is Enterprise-only. A Worker is the
 * pragmatic free-tier path:
 *
 *   browser → signal-scout.com (Cloudflare orange cloud)
 *           → this Worker (rewrites Host header)
 *           → signal-scout.run.app (Cloud Run)
 *
 * Free tier: 100k requests/day. Current production traffic is well
 * below that; bump to Workers Paid ($5/mo, 10M requests) when growth
 * warrants.
 *
 * Deployment instructions: see ../docs/cloudflare-worker-setup.md.
 */

const ORIGIN_HOST = 'signal-scout.run.app';

// Headers we never want to forward upstream — they confuse Cloud
// Run's IAM + ProxyFix when the Worker has already terminated TLS.
const STRIP_REQUEST_HEADERS = new Set([
  'cf-connecting-ip',
  'cf-ipcountry',
  'cf-ray',
  'cf-visitor',
  // host is rewritten explicitly below
]);

// Headers Cloudflare adds to RESPONSES that we want to keep stripped
// before returning to the client (Worker doesn't strictly need to
// strip these — Cloudflare itself adds them again on egress — but
// keeps the surface clean during local debug).
const STRIP_RESPONSE_HEADERS = new Set([
  'cf-cache-status',
  'cf-ray',
]);

export default {
  /**
   * @param {Request} request
   * @param {object} env
   * @param {object} ctx
   */
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // Build the upstream URL: same path + querystring, host swapped to
    // the Cloud Run service. ALWAYS https — Cloud Run only serves
    // TLS, plain http requests redirect (and that redirect would
    // carry the run.app host back to the browser, leaking the
    // origin URL).
    const upstreamUrl = new URL(url.pathname + url.search,
                                'https://' + ORIGIN_HOST);

    // Clone request headers, strip Cloudflare-injected ones, set the
    // upstream Host so the Cloud Run service sees a recognisable
    // hostname (it would 404 otherwise — Cloud Run routes by Host).
    const headers = new Headers();
    for (const [name, value] of request.headers.entries()) {
      const lname = name.toLowerCase();
      if (STRIP_REQUEST_HEADERS.has(lname)) continue;
      headers.set(name, value);
    }
    headers.set('host', ORIGIN_HOST);
    // Forward the visitor's IP as X-Forwarded-For so ProxyFix(x_for=1)
    // can use it instead of the Worker IP. Cloudflare exposes the
    // real client IP via cf-connecting-ip; we strip cf-* above and
    // re-promote it here.
    const clientIp = request.headers.get('cf-connecting-ip');
    if (clientIp) {
      const existing = request.headers.get('x-forwarded-for');
      headers.set('x-forwarded-for',
                  existing ? existing + ', ' + clientIp : clientIp);
    }
    headers.set('x-forwarded-proto', 'https');
    headers.set('x-forwarded-host', url.host);

    // Re-issue the request upstream. Body, method, redirect mode all
    // forwarded; we use 'manual' for redirect handling so 302s from
    // the app reach the browser exactly as the app intended (e.g.
    // OAuth callback's 302 to /account must keep the signal-scout.com
    // host, not get rewritten by the Worker).
    let upstreamResponse;
    try {
      upstreamResponse = await fetch(upstreamUrl.toString(), {
        method: request.method,
        headers,
        body: request.method === 'GET' || request.method === 'HEAD'
              ? undefined : request.body,
        redirect: 'manual',
      });
    } catch (err) {
      // Worker should never crash the user's request — fail soft with
      // a clear error so the user knows it's our infrastructure, not
      // their browser. Logged in Cloudflare Workers tail.
      console.error('worker upstream fetch failed:', err && err.stack);
      return new Response(
        '<h1>Service temporarily unavailable</h1>'
        + '<p>signal-scout.com upstream returned an error. Try again in a moment.</p>',
        { status: 502, headers: { 'content-type': 'text/html; charset=utf-8' } },
      );
    }

    // Mirror the response back to the browser. Filter out Cloudflare-
    // specific response headers so the user sees a clean response.
    const respHeaders = new Headers();
    for (const [name, value] of upstreamResponse.headers.entries()) {
      if (STRIP_RESPONSE_HEADERS.has(name.toLowerCase())) continue;
      respHeaders.set(name, value);
    }

    // Rewrite Location header on 3xx so redirects land on the
    // signal-scout.com host, not the run.app one. The app generates
    // absolute URLs via url_for(... _external=True) which under
    // ProxyFix uses the X-Forwarded-Host we set above — so this is
    // typically already correct. Belt-and-suspenders for any handler
    // that hardcodes the run.app URL (none today, but cheap insurance).
    const location = respHeaders.get('location');
    if (location && location.includes(ORIGIN_HOST)) {
      respHeaders.set('location',
                      location.split(ORIGIN_HOST).join(url.host));
    }

    return new Response(upstreamResponse.body, {
      status: upstreamResponse.status,
      statusText: upstreamResponse.statusText,
      headers: respHeaders,
    });
  },
};
