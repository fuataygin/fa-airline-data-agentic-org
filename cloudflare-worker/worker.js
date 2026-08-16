/**
 * cloudflare-worker/worker.js
 * -----------------------------
 * A minimal, secret-free proxy so the public GitHub Pages site can fetch
 * the live FA Airline Data Google Sheet directly from a visitor's browser.
 *
 * WHY THIS EXISTS: Google's Sheets CSV-export endpoint doesn't send
 * Access-Control-Allow-Origin, so a browser fetch() straight from
 * github.io to docs.google.com is blocked by CORS (confirmed by testing).
 * This Worker sits in between: it fetches the same public CSV server-side
 * (no CORS restriction there) and re-serves it with a permissive CORS
 * header added. No API key, no secret, no write access — it only ever
 * re-serves PUBLIC sheet data, restricted to five known tab names.
 *
 * DEPLOY (free, ~2 minutes):
 *   1. dash.cloudflare.com -> sign up / log in (free tier is enough)
 *   2. Workers & Pages -> Create -> Create Worker
 *   3. Delete the placeholder code, paste this whole file in, Save & Deploy
 *   4. Copy the worker's URL (looks like https://YOUR-WORKER.YOUR-SUBDOMAIN.workers.dev)
 *   5. Paste that URL into docs/index.html where WORKER_URL is defined
 *      (see the <script> block build_site.py generates), or set it via
 *      the CF_WORKER_URL environment variable before running build_site.py
 */

const SHEET_ID = "1VdQONMwSTiBg0w6XUq7DX6HMG6xp9d9DVO03nrl-Tfk";

const ALLOWED_TABS = new Set([
  "airline_financials",
  "fleet_orders",
  "passenger_traffic",
  "route_performance",
  "aviation_incidents",
]);

export default {
  async fetch(request) {
    const url = new URL(request.url);

    if (request.method === "OPTIONS") {
      return new Response(null, { headers: corsHeaders() });
    }

    const tab = url.searchParams.get("tab");
    if (!tab || !ALLOWED_TABS.has(tab)) {
      return new Response(
        `Missing or invalid 'tab' parameter. Allowed: ${[...ALLOWED_TABS].join(", ")}`,
        { status: 400, headers: corsHeaders() }
      );
    }

    const sheetUrl =
      `https://docs.google.com/spreadsheets/d/${SHEET_ID}/gviz/tq` +
      `?tqx=out:csv&sheet=${encodeURIComponent(tab)}`;

    const upstream = await fetch(sheetUrl, { cf: { cacheTtl: 0 } });
    const csvText = await upstream.text();

    return new Response(csvText, {
      status: upstream.status,
      headers: {
        "Content-Type": "text/csv; charset=utf-8",
        "Cache-Control": "no-store",
        ...corsHeaders(),
      },
    });
  },
};

function corsHeaders() {
  return {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
  };
}
