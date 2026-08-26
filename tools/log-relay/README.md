# PlayDate log-submission relay

A small Cloudflare Worker that sits between shipped PlayDate installs and the
real Discord webhook. See the comment at the top of `src/worker.js` for why
this exists (short version: the old approach shipped the raw Discord webhook
URL in public source/binaries, which let anyone POST arbitrary content --
`@everyone` pings, fake embeds, spam -- straight to the private `#logs`
channel once they found it, no matter how often the webhook was rotated).

This is dev-only infrastructure, not part of the shipped Python app.

## One-time setup

1. `npm install -g wrangler` (needs Node.js).
2. `wrangler login` -- opens a browser to authorize against your Cloudflare
   account.
3. From this directory: `wrangler deploy`. First deploy prints the Worker's
   public URL (something like `https://playdate-log-relay.<subdomain>.workers.dev`).
4. Set the real Discord webhook as a Worker secret (never committed):
   ```
   wrangler secret put DISCORD_WEBHOOK_URL
   ```
   Paste the webhook URL from Discord (Channel Settings -> Integrations ->
   Webhooks) when prompted.
5. (Optional but recommended) Rate limiting via KV:
   ```
   wrangler kv namespace create RATE_LIMIT
   ```
   Copy the printed `id` into the commented-out `[[kv_namespaces]]` block in
   `wrangler.toml`, uncomment it, then `wrangler deploy` again.

No local Node/wrangler? Paste `src/worker.js` directly into the Cloudflare
dashboard's Workers quick-edit UI instead, then add the secret and KV
binding from the dashboard's Settings tab.

## Updating diagnostics.py

Point `RELAY_URL` in `diagnostics.py` at the Worker URL from step 3. Nothing
else in `diagnostics.py` needs a Discord credential anymore -- the real
webhook only ever lives in the Worker's secret store.

## If the relay URL itself gets spammed

Unlike the raw webhook, the Worker only ever forwards a fixed message
template (see `worker.js`) -- a caller can't inject raw Discord content,
mentions, or embeds no matter what they send. Worst case is junk text in the
template's "Message:" line, capped at 1000 chars, and rate-limited to 5
requests/hour/IP. If it's still a nuisance, lower `RATE_LIMIT_MAX_REQUESTS`
in `worker.js` and redeploy -- no need to touch `diagnostics.py` or ship a
new PlayDate release.
