import { githubRequest, readBody, sameOrigin, send, publicError } from '../lib/kidas-server.js';

export default async function handler(req, res) {
  if (req.method !== 'POST') return send(res, 405, { error: 'Méthode non autorisée.' });
  if (!sameOrigin(req)) return send(res, 403, { error: 'Origine de la demande refusée.' });
  const { releaseId, tag } = readBody(req);
  if (!/^\d+$/.test(String(releaseId || '')) || !/^[A-Za-z0-9._-]{1,100}$/.test(String(tag || ''))) {
    return send(res, 400, { error: 'Vidéo ou identifiant invalide.' });
  }
  try {
    await githubRequest(`/repos/kidasniger/Kidas/releases/${releaseId}`, { method: 'DELETE' });
    try {
      await githubRequest(`/repos/kidasniger/Kidas/git/refs/tags/${encodeURIComponent(tag)}`, { method: 'DELETE' });
    } catch (error) {
      if (error.status !== 404) throw error;
    }
    return send(res, 200, { success: true });
  } catch (error) {
    const result = publicError(error);
    return send(res, result.status, result.body);
  }
}
