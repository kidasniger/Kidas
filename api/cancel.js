import { githubRequest, readBody, sameOrigin, send, validJobId, publicError } from '../lib/kidas-server.js';

export default async function handler(req, res) {
  if (req.method !== 'POST') return send(res, 405, { error: 'Méthode non autorisée.' });
  if (!sameOrigin(req)) return send(res, 403, { error: 'Origine de la demande refusée.' });
  const { runId } = readBody(req);
  if (!/^\d+$/.test(String(runId || ''))) return send(res, 400, { error: 'Identifiant de tâche invalide.' });
  try {
    await githubRequest(`/repos/kidasniger/Kidas/actions/runs/${runId}/cancel`, { method: 'POST' });
    return send(res, 200, { success: true });
  } catch (error) {
    const result = publicError(error);
    return send(res, result.status, result.body);
  }
}
