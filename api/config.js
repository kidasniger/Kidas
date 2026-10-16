import { send } from '../lib/kidas-server.js';

export default async function handler(req, res) {
  if (req.method !== 'GET') return send(res, 405, { error: 'Méthode non autorisée.' });
  const ready = Boolean(
    process.env.KIDAS_GITHUB_TOKEN &&
    process.env.BLOB_STORE_ID &&
    process.env.VERCEL_OIDC_TOKEN &&
    process.env.TURNSTILE_SECRET_KEY
  );
  return send(res, 200, {
    ready,
    turnstileSiteKey: process.env.TURNSTILE_SITE_KEY || ''
  });
}
