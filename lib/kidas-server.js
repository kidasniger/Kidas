import { createHmac, timingSafeEqual } from 'node:crypto';

export function send(res, status, payload) {
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('X-Content-Type-Options', 'nosniff');
  return res.status(status).json(payload);
}

export function readBody(req) {
  if (req.body && typeof req.body === 'object' && !Buffer.isBuffer(req.body)) return req.body;
  if (typeof req.body === 'string') {
    try { return JSON.parse(req.body); } catch { return {}; }
  }
  return {};
}

export function sameOrigin(req) {
  const origin = req.headers.origin;
  const host = String(req.headers['x-forwarded-host'] || req.headers.host || '').split(',')[0].trim().toLowerCase();
  if (!origin || !host) return false;
  try {
    const url = new URL(origin);
    if (url.host.toLowerCase() !== host) return false;
    return url.protocol === 'https:' || (url.protocol === 'http:' && /^(localhost|127\.0\.0\.1)(:\d+)?$/.test(host));
  } catch { return false; }
}

export function validJobId(id) {
  return typeof id === 'string' && /^v[a-z0-9]{12,40}$/.test(id);
}

export function safeName(name) {
  const value = String(name || 'video')
    .replace(/\.(html?|mp4)$/i, '')
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^A-Za-z0-9._-]+/g, '_')
    .replace(/^[._-]+|[._-]+$/g, '')
    .slice(0, 80);
  return value || 'video';
}

export async function githubRequest(path, options = {}) {
  const token = process.env.KIDAS_GITHUB_TOKEN;
  if (!token) {
    const error = new Error('Le serveur doit être configuré avec le jeton GitHub KIDAS_GITHUB_TOKEN.');
    error.status = 503;
    throw error;
  }
  const headers = {
    Accept: 'application/vnd.github+json',
    Authorization: `Bearer ${token}`,
    'X-GitHub-Api-Version': '2022-11-28'
  };
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  const response = await fetch(`https://api.github.com${path}`, {
    method: options.method || 'GET',
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body)
  });
  const raw = await response.text();
  let data = null;
  if (raw) { try { data = JSON.parse(raw); } catch { data = { message: raw.slice(0, 300) }; } }
  if (!response.ok) {
    const error = new Error(
      response.status === 401 || response.status === 403
        ? 'Le jeton GitHub du serveur n’a pas les autorisations nécessaires (Actions et Contents).'
        : (data?.message || `GitHub a répondu ${response.status}.`)
    );
    error.status = response.status;
    throw error;
  }
  return { status: response.status, data };
}

export async function verifyTurnstile(req, token) {
  if (!process.env.TURNSTILE_SECRET_KEY) {
    const error = new Error('La protection anti-robot n’est pas configurée sur le serveur.');
    error.status = 503;
    throw error;
  }
  if (typeof token !== 'string' || token.length < 10 || token.length > 4096) {
    const error = new Error('Validation de sécurité manquante. Réessaie.');
    error.status = 403;
    throw error;
  }
  const body = new URLSearchParams({ secret: process.env.TURNSTILE_SECRET_KEY, response: token });
  const ip = String(req.headers['x-forwarded-for'] || '').split(',')[0].trim();
  if (ip) body.set('remoteip', ip);
  const response = await fetch('https://challenges.cloudflare.com/turnstile/v0/siteverify', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok || !result.success) {
    const error = new Error('La vérification anti-robot a échoué. Réessaie.');
    error.status = 403;
    throw error;
  }
}

export function publicError(error) {
  const status = Number(error?.status) || 500;
  const safeMessage = status >= 500 && status !== 503
    ? 'Le serveur n’a pas pu terminer la demande. Réessaie dans un instant.'
    : (error?.message || 'Erreur inconnue.');
  return { status, body: { error: safeMessage } };
}

/**
 * Very short-lived, per-file capabilities for GitHub Actions.
 * The signing key never leaves Vercel; the GitHub run receives only a scoped signature.
 */
export function signWorkflowCapability(action, id, expires) {
  const secret = process.env.KIDAS_GITHUB_TOKEN;
  if (!secret) {
    const error = new Error('Le serveur doit être configuré avec le jeton GitHub KIDAS_GITHUB_TOKEN.');
    error.status = 503;
    throw error;
  }
  return createHmac('sha256', secret)
    .update(`kidas-v1:${action}:${id}:${expires}`)
    .digest('hex');
}

export function verifyWorkflowCapability(action, id, expires, signature) {
  if (!validJobId(id) || !/^\\d{13}$/.test(String(expires)) ||
      !/^[a-f0-9]{64}$/.test(String(signature || ''))) return false;
  const expiry = Number(expires);
  if (!Number.isSafeInteger(expiry) || expiry <= Date.now() ||
      expiry > Date.now() + 2 * 60 * 60 * 1000) return false;
  try {
    const expected = Buffer.from(signWorkflowCapability(action, id, String(expiry)), 'hex');
    const supplied = Buffer.from(String(signature), 'hex');
    return expected.length === supplied.length && timingSafeEqual(expected, supplied);
  } catch {
    return false;
  }
}
