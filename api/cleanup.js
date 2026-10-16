import { del } from '@vercel/blob';
import { readBody, sameOrigin, send, validJobId, verifyWorkflowCapability, publicError } from '../lib/kidas-server.js';

export default async function handler(req, res) {
  if (req.method !== 'POST') return send(res, 405, { error: 'Méthode non autorisée.' });
  const { id, expires, signature } = readBody(req);
  if (!validJobId(id)) return send(res, 400, { error: 'Identifiant temporaire invalide.' });
  const workflowAuthorized = verifyWorkflowCapability('cleanup', id, String(expires || ''), String(signature || ''));
  if (!sameOrigin(req) && !workflowAuthorized) return send(res, 403, { error: 'Lien de nettoyage invalide ou expiré.' });
  try {
    await del(`incoming/${id}.html`);
    return send(res, 200, { success: true });
  } catch (error) {
    const result = publicError(error);
    return send(res, result.status, result.body);
  }
}
