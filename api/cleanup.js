import { del } from '@vercel/blob';
import { readBody, sameOrigin, send, validJobId, publicError } from '../lib/kidas-server.js';
import { timingSafeEqual } from 'node:crypto';

function validInternalToken(req) {
  const expected = process.env.BLOB_READ_WRITE_TOKEN || '';
  const supplied = String(req.headers.authorization || '').replace(/^Bearer\s+/i, '');
  if (!expected || supplied.length !== expected.length) return false;
  try { return timingSafeEqual(Buffer.from(supplied), Buffer.from(expected)); } catch { return false; }
}

export default async function handler(req, res) {
  if (req.method !== 'POST') return send(res, 405, { error: 'Méthode non autorisée.' });
  if (!sameOrigin(req) && !validInternalToken(req)) return send(res, 403, { error: 'Origine de la demande refusée.' });
  const { id } = readBody(req);
  if (!validJobId(id)) return send(res, 400, { error: 'Identifiant temporaire invalide.' });
  try {
    await del(`incoming/${id}.html`);
    return send(res, 200, { success: true });
  } catch (error) {
    const result = publicError(error);
    return send(res, result.status, result.body);
  }
}
