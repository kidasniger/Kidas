import { send } from '../lib/kidas-server.js';

export default async function handler(req, res) {
  if (req.method !== 'GET') return send(res, 405, { error: 'Méthode non autorisée.' });
  const required = {
    KIDAS_GITHUB_TOKEN: process.env.KIDAS_GITHUB_TOKEN,
    BLOB_STORE_ID: process.env.BLOB_STORE_ID,
    TURNSTILE_SITE_KEY: process.env.TURNSTILE_SITE_KEY,
    TURNSTILE_SECRET_KEY: process.env.TURNSTILE_SECRET_KEY
  };
  const missing = Object.entries(required)
    .filter(([, value]) => !String(value || '').trim())
    .map(([name]) => name);
  return send(res, 200, {
    ready: missing.length === 0,
    missing,
    turnstileSiteKey: process.env.TURNSTILE_SITE_KEY || ''
  });
}
