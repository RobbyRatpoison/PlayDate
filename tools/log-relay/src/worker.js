// PlayDate log-submission relay.
//
// Runs on Cloudflare Workers. Sits between every shipped PlayDate install
// and the real Discord webhook, which is now a Worker secret (never in
// source, never in the built app) instead of a constant baked into
// diagnostics.py. Clients hit this Worker's URL instead -- that URL is just
// as public/discoverable as the old raw webhook URL was, but discovering it
// no longer hands out a "post anything to our Discord" credential:
//
//   - Only a fixed request shape is accepted (one log file + a few short
//     text fields); everything else is dropped on the floor.
//   - The Discord message content is always built from a Worker-side
//     template. A caller's "message" field only ever lands inside one line
//     of that template as plain text -- it can never become raw `content`,
//     an embed, a username/avatar override, or anything else Discord's
//     webhook payload schema allows.
//   - `allowed_mentions: {parse: []}` is set unconditionally, so even an
//     "@everyone" typed into the message field can't ping the channel.
//   - Simple per-IP rate limiting (KV-backed) blunts burst floods like the
//     one that prompted this -- five messages in twelve seconds.
//
// Deploy: see README.md in this directory.

const MAX_LOG_BYTES = 1024 * 1024; // matches RotatingFileHandler cap
const MAX_MESSAGE_CHARS = 1000;
const MAX_SHORT_FIELD_CHARS = 100;

// Targets burst floods (the actual incident: 5 messages in ~12 seconds),
// not sustained legitimate use -- PlayDate's own SUBMIT_COOLDOWN_SECONDS
// (5 min) already caps a single install to one submission per 5 minutes,
// so a short window here just needs to catch scripted bursts without
// punishing normal use from a shared IP (household, office, CGNAT).
const RATE_LIMIT_WINDOW_SECONDS = 60; // 1 minute
const RATE_LIMIT_MAX_REQUESTS = 3; // per IP per window

function truncate(value, max) {
  if (typeof value !== 'string') return '';
  return value.replace(/[\r\n]+/g, ' ').trim().slice(0, max);
}

async function checkRateLimit(env, ip) {
  if (!env.RATE_LIMIT) return true; // KV not bound -- fail open, don't hard-block submissions
  const key = `rl:${ip}`;
  const raw = await env.RATE_LIMIT.get(key);
  const count = raw ? parseInt(raw, 10) : 0;
  if (count >= RATE_LIMIT_MAX_REQUESTS) return false;
  await env.RATE_LIMIT.put(key, String(count + 1), { expirationTtl: RATE_LIMIT_WINDOW_SECONDS });
  return true;
}

export default {
  async fetch(request, env) {
    if (request.method !== 'POST') {
      return new Response('Method not allowed', { status: 405 });
    }

    if (!env.DISCORD_WEBHOOK_URL) {
      return Response.json({ status: 'error', message: 'Relay is not configured.' }, { status: 501 });
    }

    const ip = request.headers.get('CF-Connecting-IP') || 'unknown';
    if (!(await checkRateLimit(env, ip))) {
      return Response.json({ status: 'error', message: 'Too many submissions. Try again later.' }, { status: 429 });
    }

    let form;
    try {
      form = await request.formData();
    } catch {
      return Response.json({ status: 'error', message: 'Malformed request.' }, { status: 400 });
    }

    const file = form.get('file');
    if (!(file instanceof File)) {
      return Response.json({ status: 'error', message: 'Missing log file.' }, { status: 400 });
    }
    const logBuf = await file.arrayBuffer();
    if (logBuf.byteLength === 0 || logBuf.byteLength > MAX_LOG_BYTES) {
      return Response.json({ status: 'error', message: 'Log file missing or too large.' }, { status: 400 });
    }

    let meta = {};
    const metaRaw = form.get('meta');
    if (typeof metaRaw === 'string') {
      try {
        meta = JSON.parse(metaRaw);
      } catch {
        meta = {};
      }
    }

    const message = truncate(meta.message, MAX_MESSAGE_CHARS);
    const version = truncate(meta.version, MAX_SHORT_FIELD_CHARS) || 'unknown';
    const installChannel = truncate(meta.install_channel, MAX_SHORT_FIELD_CHARS) || 'unknown';
    const os = truncate(meta.os, MAX_SHORT_FIELD_CHARS) || 'unknown';

    let content = '**PlayDate log submission**\n' +
      `Version: ${version} (${installChannel})\n` +
      `OS: ${os}\n`;
    if (message) content += `Message: ${message}\n`;

    const discordForm = new FormData();
    discordForm.append('payload_json', JSON.stringify({
      content,
      allowed_mentions: { parse: [] },
    }));
    discordForm.append('file', new Blob([logBuf], { type: 'text/plain' }), 'playdate.log');

    let discordResp;
    try {
      discordResp = await fetch(env.DISCORD_WEBHOOK_URL, { method: 'POST', body: discordForm });
    } catch {
      return Response.json({ status: 'error', message: 'Could not reach the report server.' }, { status: 502 });
    }

    if (!discordResp.ok) {
      return Response.json({ status: 'error', message: 'Could not reach the report server.' }, { status: 502 });
    }

    return Response.json({ status: 'success' });
  },
};
