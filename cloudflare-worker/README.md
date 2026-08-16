# Live browser widget — Cloudflare Worker setup

`docs/index.html` includes a "Live in your browser" section that
re-fetches the public FA Airline Data sheet directly in each visitor's
browser and recomputes a simplified risk score client-side, right when
they load the page — a genuinely live data connection, safe to publish
with no login required.

It needs one small piece of free infrastructure to work around a browser
limitation (Google's sheet-export endpoint doesn't send CORS headers, so
a browser can't fetch it directly). `worker.js` in this folder is a tiny,
secret-free proxy that fixes that.

## Deploy it (about 2 minutes, free)

1. Go to **dash.cloudflare.com** and sign up (or log in) — the free tier
   is more than enough for this.
2. In the sidebar, click **Workers & Pages** → **Create** → **Create Worker**.
3. Give it any name (e.g. `faad-sheet-proxy`) → **Deploy** (it deploys a
   placeholder first, that's fine).
4. Click **Edit code**. Delete everything in the editor and paste in the
   full contents of `worker.js` from this folder. Click **Save and Deploy**.
5. Copy the URL Cloudflare shows you — it looks like:
   ```
   https://faad-sheet-proxy.YOUR-SUBDOMAIN.workers.dev
   ```

## Wire it into the site

Set it as an environment variable before building the site:

```bash
export CF_WORKER_URL="https://faad-sheet-proxy.YOUR-SUBDOMAIN.workers.dev"
python build_site.py
```

`build_site.py` bakes that URL into `docs/index.html`'s live widget. If
`CF_WORKER_URL` isn't set, the widget still renders but shows a note
explaining the worker isn't configured yet, instead of failing silently.

Commit and push `docs/` afterward as usual.

## What this Worker can and can't do

- It can only return one of five specific, hardcoded public tab names —
  it is not an open proxy for arbitrary URLs.
- It holds no API key, no credential, nothing secret. There's nothing in
  it that would matter if it were fully public (it already is).
- It only reads the sheet; it can't write to it.
